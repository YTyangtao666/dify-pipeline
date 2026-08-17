#!/usr/bin/env python3
"""FastAPI 服务化：把 01-04 脚本暴露为 HTTP 接口，供 Dify HTTP 节点调用。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

app = FastAPI(title="dify-pipeline API", version="1.0.0")

PY = sys.executable


def run(cmd: list[str], timeout: int = 1800) -> dict:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    return {"code": r.returncode, "out": r.stdout[-2000:], "err": r.stderr[-500:]}


def respond(res: dict):
    """失败码透传：脚本非零退出 → HTTP 502，让 Dify HTTP 节点如实失败。"""
    if res.get("code", 0) != 0:
        return JSONResponse(res, status_code=502)
    return res


@app.get("/health")
def health():
    return {"ok": True, "service": "dify-pipeline"}


@app.post("/scrape")           # 01 抓商品
def scrape(keyword: str = "保温杯", limit: int = 5):
    return respond(run([PY, "scripts/01_scrape_products.py", "--keyword", keyword, "--limit", str(limit)]))


@app.post("/generate")         # 02 生图（mode: styles=3风格×2张 / screens=8屏视觉逼单）
def generate(limit: int = 2, mode: str = "styles"):
    return respond(run([PY, "scripts/02_generate_images.py", "--limit", str(limit), "--mode", mode]))


@app.post("/evaluate")         # 03 评分
def evaluate():
    return respond(run([PY, "scripts/03_eval_images.py"]))


@app.post("/analyze/{pid}")    # 05 前八层分析链（L1产品→L2竞品→L6反馈→L7排序→L8brief）
def analyze(pid: str, full: bool = True):
    cmd = [PY, "scripts/05_analyze.py", "--product", pid]
    if not full:
        cmd += ["--no-competitor", "--no-feedback"]
    return respond(run(cmd, timeout=1200))


@app.post("/video/{pid}")      # 04 视频（script_category 可选：脚本库分类驱动口播）
def video(pid: str, script_category: str | None = None):
    cmd = [PY, "scripts/04_make_video.py", "--product", pid]
    if script_category:
        cmd += ["--script-category", script_category]
    return respond(run(cmd))


@app.post("/import-results/{pid}")  # L10 导入投放数据（body: {"file": "data/ads.csv"}）
def import_results(pid: str, file: str):
    return respond(run([PY, "scripts/07_import_results.py", "--product", pid, "--file", file]))


@app.post("/iterate/{pid}")        # L11 归因迭代 → 框架库 score 回流
def iterate(pid: str):
    return respond(run([PY, "scripts/08_iterate.py", "--product", pid], timeout=600))


@app.get("/report")            # 读取最新评分报告（Dify 条件分支取数用）
def report():
    f = ROOT / "output/eval/eval_report.json"
    if not f.exists():
        return JSONResponse({"error": "no report yet"}, status_code=404)
    import json
    return json.loads(f.read_text(encoding="utf-8"))




# ── 资产上传与一键组图（图生图） ────────────────────────────────
import json
import os
from fastapi import UploadFile, File, HTTPException
from scripts.pipeline import compose as compose_lib

ASSETS_DIR = ROOT / "data" / "assets"
ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


@app.post("/assets/{pid}/{kind}")  # kind: white=白底图 model=模特图
async def upload_asset(pid: str, kind: str, file: UploadFile = File(...)):
    if kind not in ("white", "model"):
        raise HTTPException(400, f"kind 须为 white/model，收到 {kind}")
    ext = ALLOWED_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(415, f"仅支持 png/jpeg/webp，收到 {file.content_type}")
    d = ASSETS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    # 同类资产多张：white_1.png white_2.png …
    n = len(list(d.glob(f"{kind}_*"))) + 1
    dest = d / f"{kind}_{n}{ext}"
    dest.write_bytes(await file.read())
    try:
        rel = str(dest.relative_to(ROOT))
    except ValueError:  # 测试环境 ASSETS_DIR 在 /tmp
        rel = str(dest)
    return {"ok": True, "kind": kind, "path": rel, "count": n}


@app.get("/assets/{pid}")
def list_assets(pid: str):
    d = ASSETS_DIR / pid
    if not d.exists():
        return {"white": 0, "model": 0, "files": []}
    files = sorted(p.name for p in d.iterdir() if p.is_file())
    return {"white": sum(1 for f in files if f.startswith("white")),
            "model": sum(1 for f in files if f.startswith("model")),
            "files": files}


@app.get("/compose/presets")
def compose_presets():
    return {"presets": compose_lib.pick_presets(compose_lib.list_presets())}


@app.post("/generate/compose")  # 一键组图：白底图/模特图 × 选中的构图预设
def generate_compose(body: dict):
    pid = body.get("product_id", "")
    presets = body.get("presets") or []
    d = ASSETS_DIR / pid
    whites = sorted(d.glob("white_*")) if d.exists() else []
    models = sorted(d.glob("model_*")) if d.exists() else []
    if not whites:
        return JSONResponse({"detail": f"商品 {pid} 未上传白底图，先 POST /assets/{pid}/white"},
                            status_code=400)
    if not presets:
        presets = ["main_white", "scene_lifestyle", "model_hold", "detail_closeup"]

    # Top3 卖点注入（L7 数据存在时）
    top3 = []
    sp = ROOT / "data" / f"selling_points_{pid}.json"
    if sp.exists():
        try:
            top3 = [t["point"] for t in json.loads(sp.read_text(encoding="utf-8")).get("top3", [])]
        except Exception:  # noqa: BLE001
            pass
    titles = {p["product_id"]: p.get("title", pid)
              for p in json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))}
    title = titles.get(pid, pid)

    import asyncio
    from scripts.pipeline import imagegen
    from scripts.pipeline.config import Config
    cfg = Config.from_env()
    manifest = {"generated": [], "failed": []}

    async def _gen_one(pid_preset, preset, refs, fname):
        async with imagegen.build_client(cfg) as client:
            return await imagegen.generate_image(
                cfg, prompt, fname, size=preset["size"], interval=1.0,
                client=client, reference_images=refs)

    for pid_preset in presets:
        preset = compose_lib.PRESETS.get(pid_preset)
        if not preset:
            manifest["failed"].append({"preset": pid_preset, "error": "未知预设"})
            continue
        refs = whites[:1] + (models[:1] if "model" in preset["uses"] else [])
        prompt = compose_lib.build_prompt(pid_preset, title=title, top3_points=top3 or None)
        fname = ROOT / "output" / "images" / f"{pid}_{pid_preset}.png"
        try:
            r = asyncio.run(_gen_one(pid_preset, preset, refs, fname))
            manifest["generated"].append(str(r.path.relative_to(ROOT)))
            print(f"  ✓ {pid_preset} ({preset['name']})")
        except Exception as e:  # noqa: BLE001
            manifest["failed"].append({"preset": pid_preset, "error": str(e)[:200]})
            print(f"  ✗ {pid_preset}: {str(e)[:120]}")
    ok = len(manifest["generated"])
    if ok == 0:
        return JSONResponse(manifest, status_code=502)
    manifest["summary"] = {"ok": ok, "failed": len(manifest["failed"])}
    return manifest


from fastapi.responses import FileResponse


@app.get("/file")  # 前端展示生成图（仅限 output/ 下，防穿越）
def serve_output_file(path: str):
    f = (ROOT / path).resolve()
    if not str(f).startswith(str(ROOT / "output")) or not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f)




# ── 套餐（Bundle）批量生产 ─────────────────────────────────────
from scripts.pipeline import bundles as bundles_lib
from scripts.pipeline import runner as runner_lib


@app.get("/bundles")  # 套餐列表 + 该商品的实时可跑性/成本预估
def list_bundles(product_id: str = "P001"):
    out = []
    for bid in bundles_lib.BUNDLES:
        b = bundles_lib.get_bundle(bid)
        plan = bundles_lib.plan_bundle(product_id, bid, assets_dir=ASSETS_DIR)
        out.append({"bundle_id": bid, "name": b["name"], "desc": b.get("desc", ""),
                    "slots": len(b["slots"]),
                    "plan": {"total": len(plan.slots), "total_runnable": plan.total_runnable,
                             "estimated_credits": plan.estimated_credits,
                             "estimated_seconds": plan.estimated_seconds}})
    return {"bundles": out}


@app.post("/generate/bundle")  # 执行套餐（retry_failed=true 只重跑失败槽位）
def generate_bundle(body: dict):
    pid = body.get("product_id", "")
    bid = body.get("bundle", "")
    if bid not in bundles_lib.BUNDLES:
        return JSONResponse({"detail": f"未知套餐 {bid}"}, status_code=400)
    plan = bundles_lib.plan_bundle(pid, bid, assets_dir=ASSETS_DIR,
                                   variants=int(body.get("variants", 1)))
    if plan.total_runnable == 0:
        return JSONResponse({"detail": f"商品 {pid} 无可跑槽位（缺白底图？），先上传素材"},
                            status_code=400)
    out_dir = ROOT / "output" / "bundles" / f"{pid}_{bid}"
    manifest = runner_lib.run_bundle(plan, out_dir=out_dir,
                                     retry_failed=bool(body.get("retry_failed")))
    ok = manifest["summary"]["ok"]
    if ok == 0:
        return JSONResponse(manifest, status_code=502)
    return manifest


@app.get("/bundle/{pid}/{bid}/status")  # 查询某套餐 manifest
def bundle_status(pid: str, bid: str):
    mf = ROOT / "output" / "bundles" / f"{pid}_{bid}" / "manifest.json"
    if not mf.exists():
        return {"state": "not_started"}
    m = json.loads(mf.read_text(encoding="utf-8"))
    s = m.get("summary", {})
    m["state"] = ("done" if s.get("failed", 1) == 0 and s.get("ok", 0) > 0
                  else "partial" if s.get("ok", 0) > 0 else "failed")
    return m




# ── 风格技能包（Style Skill）──
import time as _time_mod
from fastapi import Form
from scripts.pipeline import style_learner as style_learner_lib


@app.post("/skills/learn")  # 上传样例图集 → 学习 → 技能包
def learn_skill(skill_id: str = Form(""), name: str = Form(""),
                files: list[UploadFile] = File(...)):
    if not skill_id:
        skill_id = f"style_{int(_time_mod.time())}"
    d = ASSETS_DIR / "_samples" / skill_id
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        ext = ALLOWED_TYPES.get(f.content_type or "")
        if not ext:
            continue
        p = d / f"{len(saved)+1}{ext}"
        p.write_bytes(f.file.read())
        saved.append(p)
    if not saved:
        return JSONResponse({"detail": "未收到有效图片(png/jpeg/webp)"}, status_code=415)
    pack = style_learner_lib.learn_from_dir(
        d, skill_id=skill_id, name=name or skill_id, data_dir=ROOT / "data")
    return {"skill_id": pack["skill_id"], "name": pack["name"],
            "slots": [{"pos": s["pos"], "role": s["role"], "size": s["size"],
                       "input_deps": s["input_deps"]} for s in pack["slots"]],
            "samples": len(saved)}


@app.get("/skills")  # 技能包列表
def list_skills():
    d = ROOT / "data" / "skills"
    out = []
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                pack = json.loads(f.read_text(encoding="utf-8"))
                out.append({"skill_id": pack["skill_id"], "name": pack.get("name", ""),
                            "slots": len(pack.get("slots", [])),
                            "created": pack.get("created", "")})
            except Exception:  # noqa: BLE001
                continue
    return {"skills": out}


@app.post("/generate/skill")  # 技能包 × 商品素材 → 一键批量生成
def generate_by_skill(body: dict):
    skill_id = body.get("skill_id", "")
    pid = body.get("product_id", "")
    try:
        pack = style_learner_lib.load_skill_pack(skill_id, data_dir=ROOT / "data")
    except FileNotFoundError:
        try:
            pack = style_learner_lib.load_skill_pack(skill_id, data_dir=ASSETS_DIR)
        except FileNotFoundError:
            return JSONResponse({"detail": f"技能包不存在: {skill_id}"}, status_code=404)

    adir = ASSETS_DIR / pid
    have = set()
    if adir.exists():
        for kind in ("white", "flat", "model", "onbody"):
            if list(adir.glob(f"{kind}_*")):
                have.add(kind)
    runnable = [s for s in pack["slots"]
                if set(s["input_deps"]) <= have]
    if not runnable:
        need = set()
        for s in pack["slots"]:
            need |= set(s["input_deps"])
        return JSONResponse({"detail": f"商品 {pid} 缺素材：需要 {sorted(need)}，"
                                        f"已有 {sorted(have)}"}, status_code=400)

    # 商品文字数据注入（灵活：有什么注入什么）
    titles = {}
    products_f = ROOT / "data" / "products.json"
    if products_f.exists():
        titles = {p["product_id"]: p.get("title", "") for p in json.loads(products_f.read_text(encoding="utf-8"))}
    selling = []
    sp_f = ROOT / "data" / f"selling_points_{pid}.json"
    if sp_f.exists():
        try:
            selling = [t["point"] for t in json.loads(sp_f.read_text(encoding="utf-8")).get("top3", [])]
        except Exception:  # noqa: BLE001
            pass
    sp_block = ("画面需视觉可见地传达卖点：" + "；".join(selling[:3]) + "。") if selling else ""

    from scripts.pipeline.bundles import BundlePlan, SlotPlan
    slots = [SlotPlan(pos=s["pos"], role=s["role"], preset=f"skill:{skill_id}:{s['pos']}",
                      size=s["size"],
                      filename=f"{pid}_{s['pos']:02d}_{s['role']}.png",
                      runnable=True) for s in runnable]
    plan = BundlePlan(bundle_id=f"skill_{skill_id}", product_id=pid, slots=slots)
    out_dir = ROOT / "output" / "bundles" / f"{pid}_{skill_id}"
    # runner 的 prompt 构建：技能槽位走 pack template
    import scripts.pipeline.runner as _r
    _orig = _r._build_slot_prompt

    def _skill_prompt(plan2, slot, compose_lib, _pack=pack, _titles=titles,
                      _sp=sp_block, _orig=_orig):
        for s in _pack["slots"]:
            if s["pos"] == slot.pos:
                t = s["template"].format(
                    title=_titles.get(plan2.product_id, plan2.product_id),
                    selling_points=_sp)
                return t
        return _orig(plan2, slot, compose_lib)

    _r._build_slot_prompt = _skill_prompt
    try:
        manifest = runner_lib.run_bundle(plan, out_dir=out_dir,
                                         retry_failed=bool(body.get("retry_failed")))
    finally:
        _r._build_slot_prompt = _orig
    ok = manifest["summary"]["ok"]
    skipped = len(pack["slots"]) - len(runnable)
    manifest["summary"]["skipped"] = skipped
    if ok == 0:
        return JSONResponse(manifest, status_code=502)
    return manifest


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8100")))
