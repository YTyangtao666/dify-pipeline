#!/usr/bin/env python3
"""04 视频合成：每商品 取可用图 + 口播TTS → FFmpeg → output/videos/{pid}.mp4"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline import evaluator as evaluator_mod  # noqa: E402
from scripts.pipeline import scraper, videogen  # noqa: E402
from scripts.pipeline.config import Config  # noqa: E402

MAX_IMAGES = 4  # 每视频最多用几张图


async def run(pid: str, images_dir: Path, eval_dir: Path, videos_dir: Path,
              products_file: Path, per_image_sec: float,
              script_category: str | None = None, script_seed: int = 0) -> Path | None:
    cfg = Config.from_env()

    # 可用图优先；没有评分报告则全用
    report_file = eval_dir / "eval_report.json"
    usable: list[str] | None = None
    if report_file.exists():
        report = json.loads(report_file.read_text(encoding="utf-8"))
        items = report.get("products", {}).get(pid, {}).get("items", [])
        usable = [it["image"] for it in items if it.get("usable")]

    # 8屏模式的文件名不同（screen1_首屏定位），两种都支持
    candidates = sorted(images_dir.glob(f"{pid}_screen*.png")) or sorted(images_dir.glob(f"{pid}_*.png"))
    if usable:
        chosen = [images_dir / u for u in usable if (images_dir / u).exists()]
    else:
        chosen = candidates
    if not chosen:
        print(f"[04] {pid} 没有可用图片，跳过")
        return None
    chosen = chosen[:MAX_IMAGES]

    # 商品信息
    products = json.loads(products_file.read_text(encoding="utf-8")) if products_file.exists() else []
    product = next((p for p in products if p.get("product_id") == pid), {"product_id": pid, "title": pid})

    # 口播文案：脚本库优先（--script-category），否则模板
    plan = None
    if script_category is not None:
        from scripts.pipeline import video_script as vs
        try:
            lib = vs.default_library()
            tpl = lib.pick(script_category, seed=script_seed)
            plan = vs.build_video_plan(tpl, product_title=product.get("title", ""))
        except FileNotFoundError:
            print("[04] ⚠️ 脚本库缺失，回退模板口播")

    if plan:
        tts_text = plan["tts_text"]
        print(f"[04] {pid}: 脚本库#{plan['script_id']} [{plan['category']}]《{plan['topic']}》 "
              f"{len(plan['shots'])}分镜 {plan['duration_est']}s")
    else:
        script = scraper.build_video_script(product)
        tts_text = script["tts_text"]

    videos_dir.mkdir(parents=True, exist_ok=True)
    out = videos_dir / f"{pid}.mp4"
    print(f"[04] {pid}: {len(chosen)}张图 → {out.name}")
    await videogen.compose_video(
        chosen, tts_text, cfg.tts_voice, out, per_image_sec=per_image_sec)
    # 保存视频计划（分镜与提示词溯源）
    if plan:
        (videos_dir / f"{pid}.plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[04] ✓ {out}")
    return out


def main():
    ap = argparse.ArgumentParser(description="商品短视频合成")
    ap.add_argument("--product", help="指定商品ID；不指定则合成全部")
    ap.add_argument("--images", default="output/images")
    ap.add_argument("--eval", default="output/eval")
    ap.add_argument("--out", default="output/videos")
    ap.add_argument("--products", default="data/products.json")
    ap.add_argument("--per-image-sec", type=float, default=4.0)
    ap.add_argument("--script-category", default=None,
                    help="用脚本库指定分类驱动口播（如 真人博主真实种草）；缺省用模板")
    ap.add_argument("--script-seed", type=int, default=0, help="脚本选择种子（同种子可复现）")
    args = ap.parse_args()

    images_dir = ROOT / args.images
    if args.product:
        pids = [args.product]
    else:
        pids = sorted({p.name.split("_")[0] for p in images_dir.glob("*_*.png")})
    if not pids:
        print("[04] 没有可合成的商品")
        sys.exit(2)

    made = []
    for pid in pids:
        try:
            r = asyncio.run(run(pid, images_dir, ROOT / args.eval, ROOT / args.out,
                                ROOT / args.products, args.per_image_sec,
                                script_category=args.script_category,
                                script_seed=args.script_seed))
            if r:
                made.append(str(r))
        except Exception as e:  # noqa: BLE001
            print(f"[04] ✗ {pid}: {e}")
    print(f"[04] 完成 {len(made)}/{len(pids)} 个视频")


if __name__ == "__main__":
    main()
