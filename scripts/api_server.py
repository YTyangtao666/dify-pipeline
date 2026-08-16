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


@app.get("/health")
def health():
    return {"ok": True, "service": "dify-pipeline"}


@app.post("/scrape")           # 01 抓商品
def scrape(keyword: str = "保温杯", limit: int = 5):
    return run([PY, "scripts/01_scrape_products.py", "--keyword", keyword, "--limit", str(limit)])


@app.post("/generate")         # 02 生图（mode: styles=3风格×2张 / screens=8屏视觉逼单）
def generate(limit: int = 2, mode: str = "styles"):
    return run([PY, "scripts/02_generate_images.py", "--limit", str(limit), "--mode", mode])


@app.post("/evaluate")         # 03 评分
def evaluate():
    return run([PY, "scripts/03_eval_images.py"])


@app.post("/analyze/{pid}")    # 05 前八层分析链（L1产品→L2竞品→L6反馈→L7排序→L8brief）
def analyze(pid: str, full: bool = True):
    cmd = [PY, "scripts/05_analyze.py", "--product", pid]
    if not full:
        cmd += ["--no-competitor", "--no-feedback"]
    return run(cmd, timeout=1200)


@app.post("/video/{pid}")      # 04 视频（script_category 可选：脚本库分类驱动口播）
def video(pid: str, script_category: str | None = None):
    cmd = [PY, "scripts/04_make_video.py", "--product", pid]
    if script_category:
        cmd += ["--script-category", script_category]
    return run(cmd)


@app.post("/import-results/{pid}")  # L10 导入投放数据（body: {"file": "data/ads.csv"}）
def import_results(pid: str, file: str):
    return run([PY, "scripts/07_import_results.py", "--product", pid, "--file", file])


@app.post("/iterate/{pid}")        # L11 归因迭代 → 框架库 score 回流
def iterate(pid: str):
    return run([PY, "scripts/08_iterate.py", "--product", pid], timeout=600)


@app.get("/report")            # 读取最新评分报告（Dify 条件分支取数用）
def report():
    f = ROOT / "output/eval/eval_report.json"
    if not f.exists():
        return JSONResponse({"error": "no report yet"}, status_code=404)
    import json
    return json.loads(f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8100")))
