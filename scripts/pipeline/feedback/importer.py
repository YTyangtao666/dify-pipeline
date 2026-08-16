"""L10 数据测试反馈：投放数据（CTR/CVR/加购）导入 → 标准结构 test_results_{pid}.json。

方法论（十一层·第十层）：图做出来不代表有效——漂亮但不转化的图在电商里就是废图。
投放工具（千川/万象台）导出后经此标准化入库，供 L11 归因。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REQUIRED = ["image", "impressions", "clicks", "orders", "carts"]


def _validate_row(row: dict) -> dict:
    missing = [c for c in REQUIRED if c not in row]
    if missing:
        raise ValueError(f"缺少必需列: {missing}（需要 {REQUIRED}）")
    out = {"image": str(row["image"]).strip()}
    for k in ("impressions", "clicks", "orders", "carts"):
        try:
            out[k] = int(row[k])
        except (TypeError, ValueError):
            raise ValueError(f"字段 {k} 不是数字: {row[k]!r}") from None
    if out["impressions"] < 0:
        raise ValueError("impressions 不能为负")
    return out


def parse_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [_validate_row(r) for r in reader]


def parse_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("rows") or data.get("data") or []
    return [_validate_row(r) for r in data]


def derive_metrics(rows: list[dict]) -> list[dict]:
    """派生 ctr / cvr / cart_rate。"""
    out = []
    for r in rows:
        imp = r.get("impressions", 0)
        ctr = r["clicks"] / imp if imp else 0.0
        cvr = r["orders"] / r["clicks"] if r.get("clicks") else 0.0
        cart = r["carts"] / imp if imp else 0.0
        out.append({**r, "ctr": round(ctr, 4), "cvr": round(cvr, 4),
                    "cart_rate": round(cart, 4)})
    return out


def import_results(pid: str, source: Path, out_dir: Path | None = None) -> dict:
    """按后缀自动解析 → 派生指标 → 落盘 test_results_{pid}.json。"""
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        rows = parse_csv(source)
    elif suffix == ".json":
        rows = parse_json(source)
    else:
        raise ValueError(f"不支持的格式: {suffix}（仅 csv/json）")

    enriched = derive_metrics(rows)
    # 排序基准：ctr 降序（谁吸引人一眼可见）
    enriched.sort(key=lambda r: r["ctr"], reverse=True)
    result = {
        "product_id": pid,
        "source": source.name,
        "rows": enriched,
        "best": enriched[0]["image"] if enriched else None,
        "worst": enriched[-1]["image"] if enriched else None,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"test_results_{pid}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
