#!/usr/bin/env python3
"""07 导入投放数据：CSV/JSON → test_results_{pid}.json（L10）。

用法：
  python scripts/07_import_results.py --product P001 --file data/ads_results.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.feedback import importer as imp  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="导入投放数据（L10）")
    ap.add_argument("--product", required=True, help="商品ID")
    ap.add_argument("--file", required=True, help="CSV 或 JSON 文件路径")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    src = Path(args.file)
    if not src.exists():
        print(f"[07] 文件不存在: {src}")
        sys.exit(2)
    try:
        result = imp.import_results(args.product, src, out_dir=ROOT / args.out)
    except ValueError as e:
        print(f"[07] ✗ {e}")
        sys.exit(3)

    print(f"[07] ✓ 导入 {len(result['rows'])} 条 → test_results_{args.product}.json")
    for r in result["rows"][:5]:
        print(f"     {r['image']}: CTR {r['ctr']:.2%} CVR {r['cvr']:.2%}")
    print(f"     最佳: {result['best']} | 最差: {result['worst']}")


if __name__ == "__main__":
    main()
