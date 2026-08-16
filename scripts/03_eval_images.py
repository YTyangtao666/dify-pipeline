#!/usr/bin/env python3
"""03 评分：output/images/*.png → VLM 逐图判定 → output/eval/eval_report.json"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline import evaluator  # noqa: E402
from scripts.pipeline.config import Config  # noqa: E402


def load_title_map(products_file: Path) -> dict[str, str]:
    if not products_file.exists():
        return {}
    products = json.loads(products_file.read_text(encoding="utf-8"))
    return {p["product_id"]: p.get("title", "") for p in products}


def load_top3_map(data_dir: Path) -> dict[str, dict]:
    """L7 联动：读 selling_points_{pid}.json，有则升级为「打穿Top3」质检标准。"""
    mapping = {}
    for f in data_dir.glob("selling_points_*.json"):
        try:
            pid = f.stem[len("selling_points_"):]  # 防多下划线错位
            table = json.loads(f.read_text(encoding="utf-8"))
            if table.get("top3"):
                mapping[pid] = table
        except Exception:  # noqa: BLE001
            continue
    return mapping


async def run(images_dir: Path, out_dir: Path, products_file: Path) -> dict:
    cfg = Config.from_env()
    titles = load_title_map(products_file)
    top3_map = load_top3_map(products_file.parent)  # data/ 下找 selling_points_*.json
    out_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in images_dir.glob("*.png")
        if not p.name.startswith(".")
    )
    if not images:
        raise FileNotFoundError(f"{images_dir} 下没有 png")

    by_product: dict[str, list[Path]] = defaultdict(list)
    for img in images:
        by_product[img.name.split("_")[0]].append(img)

    client = None
    import httpx
    client = httpx.AsyncClient(
        base_url=cfg.base_url, headers={"Authorization": f"Bearer {cfg.api_key}"},
        proxy=cfg.proxy, timeout=120.0)

    all_verdicts = []
    reports = {}
    try:
        for pid, imgs in by_product.items():
            title = titles.get(pid, pid)
            verdicts = []
            for i, img in enumerate(imgs):
                v = await evaluator.evaluate_image(cfg, img, title, client=client,
                                                   top3_table=top3_map.get(pid))
                all_verdicts.append(v)
                verdicts.append(v)
                marks = "✓" if v.usable else "✗"
                hits = sum(1 for h in v.top3_hits if isinstance(h, dict) and h.get("hit"))
                hit_s = f" Top3打穿{hits}/{len(v.top3_hits)}" if v.top3_hits else ""
                print(f"  {marks} {img.name} score={v.score}{hit_s} "
                      f"issues={[i.get('type') for i in v.issues]}")
            reports[pid] = evaluator.build_report(verdicts)
    finally:
        await client.aclose()

    overall = evaluator.build_report(all_verdicts)
    result = {"overall": overall, "products": reports}
    out = out_dir / "eval_report.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[03] 总体可用率 {overall['usable_rate']}%  top_issue={overall['top_issue'] or '无'} → {out}")
    return result


def main():
    ap = argparse.ArgumentParser(description="VLM 图片评分")
    ap.add_argument("--images", default="output/images")
    ap.add_argument("--out", default="output/eval")
    ap.add_argument("--products", default="data/products.json")
    args = ap.parse_args()

    try:
        result = asyncio.run(run(ROOT / args.images, ROOT / args.out, ROOT / args.products))
        if result["overall"]["usable_rate"] < 80:
            print("[03] ⚠️ 可用率 < 80%，建议先优化 Prompt 再进入视频环节")
    except FileNotFoundError as e:
        print(f"[03] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
