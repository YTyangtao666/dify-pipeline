"""L7 卖点提炼与排序：卖点×痛点×竞品差异 LLM 映射 → 卖点优先级表（Top3 必打穿）。

方法论（十一层·第七层）：主图第一眼打不穿，注意力后面写再多都没用——
所以 Top3 唯一（红线3），其余卖点降级到详情页。
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm import AnalyzerConfig, chat_json

PROMPT_TEMPLATE = """请作为资深电商运营总监，基于以下三方输入，产出卖点优先级表。

【产品档案】
人群：{audience}
痛点：{pain}
场景：{scenes}
候选卖点：{selling_points}

【买家反馈（评论区提炼）】
高频痛点词：{pain_words}
高频问题：{questions}
信任缺口：{trust_gaps}

【竞品格局】
价格带：{price_band}
竞品主打：{competitor_points}
我们的差异化：{differentiation}

请严格只输出 JSON：
{{
  "priority": [
    {{
      "point": "卖点（短语，必须来自候选卖点）",
      "pain": "对应的买家痛点",
      "surface": "最佳呈现位置（主图/详情页）",
      "reason": "为什么这个位置这个优先级（一句话）",
      "score": 1-10 整数（综合 痛点强度×差异化×呈现效率）
    }}
  ]
}}

要求：
- 严格按 score 从高到低排序
- Top3 是主图必须打穿的卖点——选「痛点最强 且 与竞品有差异化」的
- 每个卖点必须对应一个真实痛点；无对应痛点的卖点 score 不得高于 5
- 只使用候选卖点清单里的内容，禁止发明新卖点"""


def _fmt_selling_points(profile: dict) -> str:
    sps = profile.get("selling_points", [])
    return "；".join(f"{s.get('point','')}（利益：{s.get('reason','')}）" for s in sps) or "（无）"


def build_prompt(profile: dict, feedback: dict | None, competitors: dict | None) -> str:
    fb = feedback or {}
    cm = competitors or {}
    pain_words = "、".join(f"{w.get('word','')}×{w.get('count','')}" for w in fb.get("pain_words", [])) or "（无）"
    questions = "；".join(fb.get("top_questions", [])) or "（无）"
    gaps = "；".join(fb.get("trust_gaps", [])) or "（无）"
    comp_points = "；".join(
        f"{c.get('title','')}：{'、'.join(c.get('main_points', []))}" for c in cm.get("competitors", [])) or "（无）"
    return PROMPT_TEMPLATE.format(
        audience=profile.get("audience", {}).get("identity", "（未知）"),
        pain=profile.get("audience", {}).get("pain", "（未知）"),
        scenes="、".join(profile.get("scenes", [])) or "（无）",
        selling_points=_fmt_selling_points(profile),
        pain_words=pain_words,
        questions=questions,
        trust_gaps=gaps,
        price_band=cm.get("price_band", "（未知）"),
        competitor_points=comp_points,
        differentiation=cm.get("differentiation", "（未分析）"),
    )


def normalize_table(pid: str, raw: dict) -> dict:
    """LLM 输出 → 优先级表。Top3 唯一性（红线3）：超过 3 个只保留前 3。"""
    items = []
    for it in raw.get("priority") or []:
        if not isinstance(it, dict):
            continue
        point = str(it.get("point", "") or "").strip()
        if not point:
            continue
        try:
            score = int(it.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        items.append({
            "point": point,
            "pain": str(it.get("pain", "") or ""),
            "surface": str(it.get("surface", "") or ""),
            "reason": str(it.get("reason", "") or ""),
            "score": max(0, min(10, score)),
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    top3 = items[:3]
    others = items[3:]
    return {
        "product_id": pid,
        "top3": top3,
        "others": others,
        "degraded": not top3,
    }


async def analyze(profile: dict, feedback: dict | None, competitors: dict | None,
                  cfg: AnalyzerConfig | None = None, out_dir: Path | None = None) -> dict:
    """产出卖点优先级表并落盘 selling_points_{pid}.json。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    pid = profile.get("product_id", "?")
    raw = await chat_json(cfg, build_prompt(profile, feedback, competitors))
    table = normalize_table(pid, raw)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / f"selling_points_{pid}.json"
        f.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return table
