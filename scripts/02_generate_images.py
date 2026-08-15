#!/usr/bin/env python3
"""02 生图：读 data/products.json → 中转站生图（3风格×2张）→ output/images/"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline import imagegen, scraper  # noqa: E402
from scripts.pipeline.config import Config  # noqa: E402

IMAGES_PER_PRODUCT = 2  # 每风格张数


async def run(products: list[dict], out_dir: Path, interval: float, limit_products: int,
              mode: str = "styles") -> dict:
    cfg = Config.from_env()
    out_dir.mkdir(parents=True, exist_ok=True)
    client = imagegen.build_client(cfg)
    manifest = {"generated": [], "failed": []}
    t0 = time.time()

    if mode == "screens":
        from scripts.pipeline import storyboard
        tasks = [(p, storyboard.build_screen_prompts(p), out_dir / f"{p['product_id']}_screen{i+1}_{pr['screen_name']}.png")
                 for p in products[:limit_products]
                 for i, pr in enumerate(storyboard.build_screen_prompts(p))]
        tasks_total = len(tasks)
        done = 0
        try:
            for product, prompts, _ in [(p, storyboard.build_screen_prompts(p), None) for p in products[:limit_products]]:
                pid = product["product_id"]
                for pr in prompts:
                    fname = out_dir / f"{pid}_screen{pr['screen_no']}_{pr['screen_name']}.png"
                    done += 1
                    try:
                        r = await imagegen.generate_image(cfg, pr["prompt"], fname, interval=interval, client=client)
                        manifest["generated"].append(str(r.path.relative_to(ROOT)))
                        print(f"  [{done}/{tasks_total}] ✓ 第{pr['screen_no']}屏 {pr['screen_name']} ({time.time()-t0:.0f}s)")
                    except Exception as e:  # noqa: BLE001
                        manifest["failed"].append({"file": fname.name, "error": str(e)[:200]})
                        print(f"  [{done}/{tasks_total}] ✗ {fname.name}: {e}")
        finally:
            await client.aclose()
    else:
        tasks_total = len(products[:limit_products]) * len(scraper.STYLES) * IMAGES_PER_PRODUCT
        done = 0
        try:
            for p in products[:limit_products]:
                pid = p["product_id"]
                for style in scraper.STYLES:
                    for k in range(1, IMAGES_PER_PRODUCT + 1):
                        prompt = scraper.build_gen_prompt(p, style)
                        fname = out_dir / f"{pid}_{_slug(style)}_{k}.png"
                        done += 1
                        try:
                            r = await imagegen.generate_image(cfg, prompt, fname, interval=interval, client=client)
                            manifest["generated"].append(str(r.path.relative_to(ROOT)))
                            print(f"  [{done}/{tasks_total}] ✓ {fname.name} ({time.time()-t0:.0f}s)")
                        except Exception as e:  # noqa: BLE001
                            manifest["failed"].append({"file": fname.name, "error": str(e)[:200]})
                            print(f"  [{done}/{tasks_total}] ✗ {fname.name}: {e}")
        finally:
            await client.aclose()

    manifest["summary"] = {
        "total": tasks_total,
        "ok": len(manifest["generated"]),
        "failed": len(manifest["failed"]),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    return manifest


def _slug(s: str) -> str:
    import re
    return re.sub(r"\W+", "", s)[:12]


def main():
    ap = argparse.ArgumentParser(description="批量生图")
    ap.add_argument("--out", default="output/images")
    ap.add_argument("--products", default="data/products.json")
    ap.add_argument("--interval", type=float, default=1.0, help="生图请求间隔秒")
    ap.add_argument("--limit", type=int, default=2, help="每批商品数（先小批量试跑）")
    ap.add_argument("--mode", choices=["styles", "screens"], default="styles",
                    help="styles=3风格×2张（旧）；screens=8屏视觉逼单详情页")
    args = ap.parse_args()

    products_file = ROOT / args.products
    if not products_file.exists():
        print(f"[02] 缺少 {products_file}，先跑 01")
        sys.exit(2)
    products = json.loads(products_file.read_text(encoding="utf-8"))
    n = min(args.limit, len(products))
    if args.mode == "screens":
        print(f"[02] 8屏视觉逼单模式: {n} 商品 × 8 屏")
    else:
        print(f"[02] 开始生图: {n} 商品 × {len(scraper.STYLES)} 风格 × {IMAGES_PER_PRODUCT} 张")

    manifest = asyncio.run(run(products, ROOT / args.out, args.interval, args.limit, mode=args.mode))

    out = ROOT / args.out / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    s = manifest["summary"]
    print(f"[02] 完成: {s['ok']}成功 {s['failed']}失败 耗时{s['elapsed_sec']}s → {out}")
    if s["ok"] == 0:
        sys.exit(3)


if __name__ == "__main__":
    main()
