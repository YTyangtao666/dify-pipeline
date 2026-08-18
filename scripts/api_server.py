#!/usr/bin/env python3
"""FastAPI 服务化：把 01-04 脚本暴露为 HTTP 接口，供 Dify HTTP 节点调用。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

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


@app.post("/assets/{pid}/prompt")  # 商品级自定义提示词（生成时注入全部槽位）
def set_custom_prompt(pid: str, body: dict):
    prompt = (body.get("custom_prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "custom_prompt 不能为空")
    if len(prompt) > 500:
        raise HTTPException(400, "custom_prompt 超过500字")
    d = ASSETS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "custom_prompt.txt").write_text(prompt, encoding="utf-8")
    return {"ok": True, "pid": pid, "custom_prompt": prompt}


@app.get("/assets/{pid}/prompt")
def get_custom_prompt(pid: str):
    f = ASSETS_DIR / pid / "custom_prompt.txt"
    if not f.exists():
        return {"custom_prompt": ""}
    return {"custom_prompt": f.read_text(encoding="utf-8")}


def _inject_custom_prompt(orig_prompt_fn, custom: str):
    """包装 _build_slot_prompt：自定义提示词追加到槽位 prompt 末尾（用户级指令优先级最高）。"""
    if not custom:
        return orig_prompt_fn

    def wrapped(plan, slot, compose_lib):
        base = orig_prompt_fn(plan, slot, compose_lib)
        return f"{base}\n【用户自定义要求·高优先级】{custom}"
    return wrapped


def _load_custom_prompt(pid: str) -> str:
    f = ASSETS_DIR / pid / "custom_prompt.txt"
    if f.exists():
        try:
            return f.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


@app.post("/assets/{pid}/{kind}")  # kind: white/model/flat/scene/ref（分类结构化素材）
async def upload_asset(pid: str, kind: str, file: UploadFile = File(...)):
    if kind not in ("white", "model", "flat", "scene", "ref"):
        raise HTTPException(400, f"kind 须为 white/model/flat/scene/ref，收到 {kind}")
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


@app.get("/assets-file/{pid}/{name}")  # 素材缩略图预览（仅限 ASSETS_DIR 防穿越）
def serve_asset_file(pid: str, name: str):
    f = (ASSETS_DIR / pid / name).resolve()
    if not str(f).startswith(str(ASSETS_DIR.resolve())) or not f.exists() or f.is_dir():
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.get("/assets/{pid}")
def list_assets(pid: str):
    d = ASSETS_DIR / pid
    if not d.exists():
        return {"white": 0, "model": 0, "flat": 0, "scene": 0, "ref": 0, "files": []}
    files = sorted(p.name for p in d.iterdir() if p.is_file())
    return {"white": sum(1 for f in files if f.startswith("white")),
            "model": sum(1 for f in files if f.startswith("model")),
            "flat": sum(1 for f in files if f.startswith("flat")),
            "scene": sum(1 for f in files if f.startswith("scene")),
            "ref": sum(1 for f in files if f.startswith("ref")),
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
    # 技能包容错：bid 带 skill_ 前缀时（历史调用习惯），映射到 {pid}_{skill_id} 目录
    if not mf.exists() and bid.startswith("skill_"):
        mf = ROOT / "output" / "bundles" / f"{pid}_{bid[len('skill_'):]}" / "manifest.json"
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




# ── 异步任务系统（技能包生成不阻塞 HTTP）──
import threading
import uuid

TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


def _run_skill_task(task_id: str, body: dict):
    """后台线程执行技能包生成，进度写 TASKS。"""
    with _TASKS_LOCK:
        TASKS[task_id]["state"] = "running"
    try:
        # 复用同步端点逻辑：直接调用其函数体（构造 Request 代价高，改为进程内直调 run）
        skill_id = body.get("skill_id", "")
        pid = body.get("product_id", "")
        pack = None
        for data_dir in (ROOT / "data", ASSETS_DIR):
            try:
                pack = style_learner_lib.load_skill_pack(skill_id, data_dir=data_dir)
                break
            except FileNotFoundError:
                continue
        if pack is None:
            raise ValueError(f"技能包不存在: {skill_id}")

        adir = ASSETS_DIR / pid
        have = set()
        if adir.exists():
            for kind in ("white", "flat", "model", "onbody", "scene", "ref"):
                if list(adir.glob(f"{kind}_*")):
                    have.add(kind)
        runnable = [s for s in pack["slots"] if set(s["input_deps"]) <= have]

        titles = {}
        products_f = ROOT / "data" / "products.json"
        if products_f.exists():
            titles = {p["product_id"]: p.get("title", "")
                      for p in json.loads(products_f.read_text(encoding="utf-8"))}
        selling = []
        sp_f = ROOT / "data" / f"selling_points_{pid}.json"
        if sp_f.exists():
            try:
                selling = [t["point"] for t in
                           json.loads(sp_f.read_text(encoding="utf-8")).get("top3", [])]
            except Exception:  # noqa: BLE001
                pass
        sp_block = ("画面需视觉可见地传达卖点：" + "；".join(selling[:3]) + "。") if selling else ""

        from scripts.pipeline.bundles import BundlePlan, SlotPlan
        from scripts.pipeline import runner as _r
        slots = [SlotPlan(pos=s["pos"], role=s["role"], preset=f"skill:{skill_id}:{s['pos']}",
                          size=s["size"], filename=f"{pid}_{s['pos']:02d}_{s['role']}.png",
                          runnable=True) for s in runnable]
        plan = BundlePlan(bundle_id=f"skill_{skill_id}", product_id=pid, slots=slots)
        out_dir = ROOT / "output" / "bundles" / f"{pid}_{skill_id}"

        _orig = _r._build_slot_prompt

        def _skill_prompt(plan2, slot, compose_lib, _pack=pack, _titles=titles,
                          _sp=sp_block, _orig=_orig):
            for s in _pack["slots"]:
                if s["pos"] == slot.pos:
                    t = s["template"].format(
                        title=_titles.get(plan2.product_id, plan2.product_id),
                        selling_points=_sp)
                    # 用户自定义提示词（最高优先级追加）
                    cp = _load_custom_prompt(pid)
                    if cp:
                        t += f"\n【用户自定义要求·高优先级】{cp}"
                    # 参照图注入说明
                    scene_refs = sorted((ASSETS_DIR / pid).glob("ref_*")) if adir.exists() else []
                    if scene_refs:
                        t += ("\n【参照图】参考图最后附带风格/构图参照图：只借鉴其风格氛围与构图思路，"
                              "商品与模特仍以商品锚定图与模特三视图为准，严禁照抄参照图中的商品与人物。")
                    return t
            return _orig(plan2, slot, compose_lib)

        _r._build_slot_prompt = _skill_prompt

        # 参照图真正注入：wrap _slot_refs，把 ref_* 追加到参考图尾部（prompt 已有对应说明）
        _orig_refs = _r._slot_refs

        def _refs_with_ref_imgs(plan2, slot, _orig=_orig_refs):
            refs = list(_orig(plan2, slot))
            ad = ASSETS_DIR / plan2.product_id
            if ad.exists():
                refs.extend(sorted(ad.glob("ref_*")))
            return refs

        _r._slot_refs = _refs_with_ref_imgs

        def _progress(kind, slot):
            with _TASKS_LOCK:
                t = TASKS.get(task_id)
                if t:
                    t["done_count"] += 1
                    t["progress"] = f"{t['done_count']}/{t['total']}"

        try:
            manifest = runner_lib.run_bundle(plan, out_dir=out_dir,
                                             retry_failed=bool(body.get("retry_failed")),
                                             on_progress=_progress)
        finally:
            _r._build_slot_prompt = _orig
            _r._slot_refs = _orig_refs
        with _TASKS_LOCK:
            TASKS[task_id].update(state="done", manifest=manifest,
                                  summary=manifest.get("summary", {}))
    except Exception as e:  # noqa: BLE001
        with _TASKS_LOCK:
            TASKS[task_id].update(state="failed", error=str(e)[:300])


@app.post("/generate/skill/async")  # 异步一键生成 → task_id
def generate_by_skill_async(body: dict):
    task_id = f"t_{uuid.uuid4().hex[:10]}"
    total = 0
    try:
        pack = style_learner_lib.load_skill_pack(body.get("skill_id", ""), data_dir=ROOT / "data")
    except FileNotFoundError:
        try:
            pack = style_learner_lib.load_skill_pack(body.get("skill_id", ""), data_dir=ASSETS_DIR)
        except FileNotFoundError:
            return JSONResponse({"detail": f"技能包不存在: {body.get('skill_id')}"}, status_code=404)
    total = len(pack["slots"]) + 2  # 槽位 + 00A/00B 锚定图余量
    # Dify/外部调用可带 custom_prompt：持久化到商品素材目录（生成时注入）
    cp = (body.get("custom_prompt") or "").strip()
    if cp:
        pd = ASSETS_DIR / body.get("product_id", "")
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "custom_prompt.txt").write_text(cp[:500], encoding="utf-8")
    with _TASKS_LOCK:
        TASKS[task_id] = {"state": "queued", "created": _time_mod.time(),
                          "total": total, "done_count": 0, "progress": f"0/{total}",
                          "body": body}
    threading.Thread(target=_run_skill_task, args=(task_id, body), daemon=True).start()
    return {"task_id": task_id, "poll": f"/tasks/{task_id}"}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    with _TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return JSONResponse({"detail": "任务不存在"}, status_code=404)
        out = {k: v for k, v in t.items() if k != "body"}
        imgs = []
        m = t.get("manifest")
        if m:
            for gp in m.get("generated", []):
                rel = str(Path(gp).relative_to(ROOT)) if str(gp).startswith(str(ROOT)) else gp
                imgs.append({"path": rel, "url": f"/file?path={rel}"})
        out["images"] = imgs
        return out


@app.get("/tasks")  # 任务列表(最近20)
def list_tasks():
    with _TASKS_LOCK:
        items = sorted(TASKS.items(), key=lambda kv: -kv[1].get("created", 0))[:20]
        return {"tasks": [{**{"task_id": k}, **{kk: vv for kk, vv in v.items()
                          if kk not in ("body", "manifest")}} for k, v in items]}


@app.get("/console")  # 极简控制台 UI
def console_ui():
    html_path = ROOT / "scripts" / "static" / "console.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8100")))
