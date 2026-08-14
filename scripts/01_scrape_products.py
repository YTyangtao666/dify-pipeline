#!/usr/bin/env python3
"""01 抓取商品数据：京东搜索(Playwright) 或 --json 兜底 → data/products.json"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline import scraper  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="抓取商品数据")
    ap.add_argument("--keyword", default="保温杯", help="京东搜索关键词")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", dest="json_file", help="兜底：直接读商品 JSON 文件")
    ap.add_argument("--out", default="data/products.json")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    args = ap.parse_args()

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.json_file:
        products = scraper.load_products(Path(args.json_file))
        print(f"[01] 从 JSON 加载 {len(products)} 个商品: {args.json_file}")
    else:
        print(f"[01] Playwright 抓取京东: keyword={args.keyword} limit={args.limit}")
        products = asyncio.run(scraper.scrape_jd(args.keyword, args.limit, headless=not args.headed))
        print(f"[01] 抓到 {len(products)} 个商品")
        if not products:
            print("[01] ⚠️ 0 结果（可能有反爬）。用 --json data/products.sample.json 兜底演示")
            sys.exit(2)

    out_path.write_text(
        json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[01] 已写入 {out_path}")
    for p in products[:5]:
        price = f"¥{p.get('price')}" if p.get("price") else "-"
        print(f"     {p['product_id']}  {price}  {p['title'][:30]}")


if __name__ == "__main__":
    main()
