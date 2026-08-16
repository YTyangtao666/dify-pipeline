#!/usr/bin/env python3
"""08 归因迭代：投放数据 × brief × Top3 → LLM 四假设归因 → 框架库 score 回流（L11）。

用法：
  python scripts/08_iterate.py --product P001
（需先跑 07 导入数据、05 产出 brief/Top3）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.analyzer.framework import default_library  # noqa: E402
from scripts.pipeline.feedback import iterator as it  # noqa: E402


async def run(pid: str, data_dir: Path) -> dict | None:
    tr_file = data_dir / f"test_results_{pid}.json"
    brief_file = data_dir / f"design_brief_{pid}.json"
    table_file = data_dir / f"selling_points_{pid}.json"
    for f, name in [(tr_file, "投放数据(先跑07)"), (brief_file, "设计brief(先跑05)"),
                    (table_file, "卖点排序(先跑05)")]:
        if not f.exists():
            print(f"[08] 缺少 {f}（{name}）")
            return None

    results = json.loads(tr_file.read_text(encoding="utf-8"))
    brief = json.loads(brief_file.read_text(encoding="utf-8"))
    table = json.loads(table_file.read_text(encoding="utf-8"))

    lib = default_library()
    wins_before = {f["id"]: f["score"].get("wins", 0) for f in [lib.get("fw_8screen_v1")] if f}

    verdict = await it.iterate(results, brief, table, lib=lib, out_dir=data_dir)

    print(f"[08] ✓ 归因完成 → iteration_{pid}.json")
    print(f"     赢家: {len(verdict['winners'])} | 输家: {len(verdict['losers'])}")
    for w in verdict["winners"][:3]:
        print(f"     + {w['image']}: {w['why'][:50]}")
    for l in verdict["losers"][:3]:
        print(f"     - {l['image']}: {l['fix'][:50]}")
    hyp = [k for k, v in verdict["hypothesis"].items() if v]
    print(f"     归因假设命中: {hyp or '无'}")
    print(f"     框架库回流: {verdict['frameworks_applied']} 条")

    fw = lib.get("fw_8screen_v1")
    if fw:
        s = fw["score"]
        print(f"     fw_8screen_v1 score: {s['wins']}胜/{s['losses']}负 "
              f"(胜率 {s.get('win_rate', 0):.0%})")
    return verdict


def main():
    ap = argparse.ArgumentParser(description="归因迭代（L11）")
    ap.add_argument("--product", required=True, help="商品ID")
    args = ap.parse_args()
    r = asyncio.run(run(args.product, ROOT / "data"))
    sys.exit(0 if r else 2)


if __name__ == "__main__":
    main()
