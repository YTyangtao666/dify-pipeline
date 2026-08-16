"""L2 竞品分析：同类目爬取 + LLM 系统对比 → 价格带/竞品卖点/差异化切口。

方法论（十一层·第二层）：主推图不是为了好看，是为了在一堆竞品里让买家先点你。
最怕自嗨——旁边的竞品比你更懂买家，你的图就白做了。
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import scraper
from .llm import AnalyzerConfig, chat_json

PROMPT_TEMPLATE = """请作为电商竞争分析师，对比我们与竞品，产出竞争定位报告。

【我们的产品】
标题：{title}
价格：{price}
描述：{desc}
类目：{category}

【竞品列表（{n}个，来自同平台搜索结果）】
{competitors}

请严格只输出 JSON：
{{
  "price_band": "该类目主流价格带（如 30-80元）",
  "our_position": "我们在价格带中的位置（低端/中端/高端）",
  "competitors": [
    {{"title": "竞品", "price": 价格, "main_points": ["主打卖点1", "主打卖点2"], "hook": "它靠什么吸引买家（一句话）"}}
  ],
  "differentiation": "我们的差异化切口（同价格带里我们独有/更强的点，一句话）",
  "attack_plan": "主图策略：面对这些竞品，我们的图应该强调什么、避开什么（2-3条）"
}}

要求：
- main_points 从竞品标题与常识卖点推断，标注为推断
- differentiation 必须与价格带挂钩（不是泛泛的「质量好」）
- attack_plan 要具体到「打哪个卖点、避哪个战场」"""


def _fmt_competitors(items: list[dict]) -> str:
    if not items:
        return "（未爬取到竞品，请按类目常识给出 3 个典型竞品画像并标注推断）"
    lines = []
    for i, c in enumerate(items, 1):
        price = c.get("price")
        price_s = f"{price}元" if price is not None else "未知价格"
        lines.append(f"{i}. {c.get('title','')}（{price_s}，{c.get('shop','')}）")
    return "\n".join(lines)


def build_prompt(product: dict, competitors: list[dict]) -> str:
    return PROMPT_TEMPLATE.format(
        title=product.get("title", ""),
        price=product.get("price") if product.get("price") is not None else "未知",
        desc=product.get("desc", "") or "（无）",
        category=product.get("category", "") or "（未分类）",
        n=len(competitors),
        competitors=_fmt_competitors(competitors),
    )


def normalize_report(pid: str, raw: dict) -> dict:
    comps = []
    for c in raw.get("competitors") or []:
        if not isinstance(c, dict) or not str(c.get("title", "")).strip():
            continue
        mps = c.get("main_points") or []
        if isinstance(mps, str):
            mps = [mps]
        try:
            price = float(c["price"]) if c.get("price") is not None else None
        except (TypeError, ValueError):
            price = None
        comps.append({"title": str(c["title"]), "price": price,
                      "main_points": [str(m) for m in mps][:4],
                      "hook": str(c.get("hook", "") or "")})
    diff = str(raw.get("differentiation", "") or "")
    return {
        "product_id": pid,
        "price_band": str(raw.get("price_band", "") or ""),
        "our_position": str(raw.get("our_position", "") or ""),
        "competitors": comps[:8],
        "differentiation": diff,
        "attack_plan": str(raw.get("attack_plan", "") or ""),
        "degraded": not (comps or diff),
    }


def collect_competitors(product: dict, limit: int = 5) -> list[dict]:
    """复用 01 的京东爬虫抓同类目。去重；失败返回空（降级）。"""
    import asyncio

    keyword = product.get("category", "") or product.get("title", "")
    try:
        items = asyncio.run(scraper.scrape_jd(keyword, limit=limit + 2))
    except Exception as e:  # noqa: BLE001
        print(f"[L2] ⚠️ 竞品爬取失败（{e}），LLM 将按常识推断")
        return []
    seen: set[str] = set()
    out = []
    my_title = product.get("title", "")
    for it in items:
        key = it.get("product_id", "") or it.get("title", "")
        if key in seen:
            continue
        seen.add(key)
        if it.get("title", "") == my_title:  # 剔除自身
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return out


async def analyze(product: dict, competitors: list[dict] | None = None,
                  cfg: AnalyzerConfig | None = None, out_dir: Path | None = None) -> dict:
    """产出 competitors_{pid}.json。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    pid = product.get("product_id", "?")
    if competitors is None:
        competitors = collect_competitors(product)
    raw = await chat_json(cfg, build_prompt(product, competitors))
    report = normalize_report(pid, raw)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"competitors_{pid}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
