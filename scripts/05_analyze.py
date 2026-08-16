#!/usr/bin/env python3
"""05 分析链：L1产品→L2竞品→L6反馈→L7卖点排序→L8设计brief（一键出 design_brief）。

方法论（十一层·前八层）：让 AI 先当运营再当美工——本脚本是"运营"部分。
单层失败降级不阻塞（红线4）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.analyzer import (brief as br, competitor as comp,
                                       feedback as fb, product as prod,
                                       selling_points as sp)
from scripts.pipeline.analyzer.llm import AnalyzerConfig


async def analyze_product(product: dict, data_dir: Path,
                          do_competitor: bool = True, do_feedback: bool = True) -> dict:
    pid = product.get("product_id", "?")
    cfg = AnalyzerConfig.from_env()
    results = {"product_id": pid, "layers": {}}

    # L1 产品分析（地基，失败则全链降级退出）
    print(f"[05] L1 产品分析: {pid}")
    profile = await prod.analyze(product, cfg=cfg, out_dir=data_dir)
    results["layers"]["L1"] = "ok" if not profile.get("degraded") else "degraded"
    print(f"     人群: {profile['audience']['identity'] or '?'} | "
          f"场景 {len(profile['scenes'])} | 卖点 {len(profile['selling_points'])}")

    # L2 竞品分析（可关）
    competitors_report = None
    if do_competitor:
        print(f"[05] L2 竞品分析: {pid}")
        try:
            competitors_report = await comp.analyze(product, cfg=cfg, out_dir=data_dir)
            results["layers"]["L2"] = "ok"
            print(f"     价格带: {competitors_report['price_band'] or '?'} | "
                  f"差异化: {competitors_report['differentiation'][:40] or '?'}")
        except Exception as e:  # noqa: BLE001
            results["layers"]["L2"] = f"failed: {e}"
            print(f"     ⚠️ 降级跳过: {e}")

    # L6 用户反馈（可关；评论采集失败自动降级空评论）
    feedback_report = None
    if do_feedback:
        print(f"[05] L6 用户反馈: {pid}")
        try:
            feedback_report = await fb.analyze(pid, cfg=cfg, out_dir=data_dir)
            results["layers"]["L6"] = "ok" if not feedback_report.get("degraded") else "degraded"
            top_pain = feedback_report["pain_words"][0]["word"] if feedback_report["pain_words"] else "?"
            print(f"     痛点Top1: {top_pain} | 信任缺口 {len(feedback_report['trust_gaps'])}")
        except Exception as e:  # noqa: BLE001
            results["layers"]["L6"] = f"failed: {e}"
            print(f"     ⚠️ 降级跳过: {e}")

    # L7 卖点排序（Top3 红线）
    print(f"[05] L7 卖点排序: {pid}")
    table = await sp.analyze(profile, feedback_report, competitors_report,
                             cfg=cfg, out_dir=data_dir)
    results["layers"]["L7"] = "ok" if not table.get("degraded") else "degraded"
    print("     Top3: " + " / ".join(t["point"] for t in table["top3"]))

    # L8 设计 brief（生图指挥官）
    print(f"[05] L8 设计方向: {pid}")
    b = await br.analyze(profile, table, cfg=cfg, out_dir=data_dir)
    results["layers"]["L8"] = "ok" if not b.get("degraded") else "degraded"
    print(f"     风格: {b['style'][:30] or '?'} | 逐屏提示词 {len(b['screen_prompts'])} 条")

    results["design_brief"] = f"design_brief_{pid}.json"
    return results


def main():
    ap = argparse.ArgumentParser(description="前八层分析链（一键出 design_brief）")
    ap.add_argument("--product", default=None, help="指定商品ID；缺省分析全部")
    ap.add_argument("--products", default="data/products.json")
    ap.add_argument("--no-competitor", action="store_true", help="跳过L2竞品（省时）")
    ap.add_argument("--no-feedback", action="store_true", help="跳过L6反馈（省爬取）")
    args = ap.parse_args()

    products_file = ROOT / args.products
    if not products_file.exists():
        print(f"[05] 缺少 {products_file}")
        sys.exit(2)
    products = json.loads(products_file.read_text(encoding="utf-8"))
    if args.product:
        products = [p for p in products if p.get("product_id") == args.product]
    if not products:
        print("[05] 无匹配商品")
        sys.exit(2)

    data_dir = ROOT / "data"
    for p in products:
        r = asyncio.run(analyze_product(p, data_dir,
                                        do_competitor=not args.no_competitor,
                                        do_feedback=not args.no_feedback))
        print(f"[05] ✓ {r['product_id']} 完成: {json.dumps(r['layers'], ensure_ascii=False)}\n")


if __name__ == "__main__":
    main()
