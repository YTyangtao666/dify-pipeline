"""L1 产品分析：商品主档 → 人群画像 / 使用场景 / 核心卖点清单。

方法论（十一层·第一层）：先让 AI 当运营——弄明白卖给谁、什么场景用、能打的卖点是什么。
产出是后续所有层的方向；没有它，做图就是让 AI 瞎猜。
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm import AnalyzerConfig, chat_json

PROMPT_TEMPLATE = """请作为资深电商运营，分析以下商品，产出运营侧产品档案（人群画像、使用场景、核心卖点清单）。

商品信息：
- 标题：{title}
- 描述：{desc}
- 价格：{price}
- 类目：{category}

请严格只输出 JSON（不要任何其他文字），结构如下：
{{
  "audience": {{
    "age": "年龄段",
    "identity": "核心人群身份（如：上班族女性/学生党/宝妈）",
    "pain": "这群人在这类商品上的核心痛点"
  }},
  "scenes": ["使用场景1", "使用场景2", "使用场景3"],
  "selling_points": [
    {{"point": "卖点（短语）", "reason": "对买家的利益翻译", "evidence": "支撑该卖点的产品事实"}}
  ]
}}

要求：
- selling_points 至少 3 条、至多 6 条，按对买家的吸引力排序
- reason 必须是买家利益（体验/省事/省钱），不是功能复述
- 只基于给出的商品事实，禁止编造参数和认证"""


def build_prompt(product: dict) -> str:
    return PROMPT_TEMPLATE.format(
        title=product.get("title", ""),
        desc=product.get("desc", "") or "（无）",
        price=product.get("price") if product.get("price") is not None else "（未知）",
        category=product.get("category", "") or "（未分类）",
    )


def normalize_profile(pid: str, raw: dict) -> dict:
    """LLM 输出 → 结构化档案。缺字段降级兜底（degraded=True），不崩溃。"""
    audience = raw.get("audience") or {}
    if not isinstance(audience, dict):
        audience = {"identity": str(audience)}
    audience = {
        "age": str(audience.get("age", "") or ""),
        "identity": str(audience.get("identity", "") or ""),
        "pain": str(audience.get("pain", "") or ""),
    }

    scenes = raw.get("scenes") or []
    if isinstance(scenes, str):
        scenes = [scenes]
    scenes = [str(s) for s in scenes][:8]

    sps_raw = raw.get("selling_points") or []
    selling_points = []
    for sp in sps_raw:
        if isinstance(sp, dict):
            selling_points.append({
                "point": str(sp.get("point", "") or ""),
                "reason": str(sp.get("reason", "") or ""),
                "evidence": str(sp.get("evidence", "") or ""),
            })
        elif isinstance(sp, str) and sp.strip():
            selling_points.append({"point": sp.strip(), "reason": "", "evidence": ""})

    degraded = not (audience["identity"] and scenes and selling_points)
    return {
        "product_id": pid,
        "audience": audience,
        "scenes": scenes,
        "selling_points": selling_points[:6],
        "degraded": degraded,
    }


async def analyze(product: dict, cfg: AnalyzerConfig | None = None,
                  out_dir: Path | None = None) -> dict:
    """分析单个商品并落盘 product_profile_{pid}.json。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    pid = product.get("product_id", "?")
    raw = await chat_json(cfg, build_prompt(product))
    profile = normalize_profile(pid, raw)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / f"product_profile_{pid}.json"
        f.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
