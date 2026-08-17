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


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8100")))
