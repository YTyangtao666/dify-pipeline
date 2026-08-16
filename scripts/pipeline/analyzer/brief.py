"""L8 设计方向：前七层全量输入 → design_brief（风格/色彩/构图/逐屏提示词/负面约束）。

方法论（十一层·第八层）：把 LLM 当设计总监——产出方向与提示词，第九层只负责执行。
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm import AnalyzerConfig, chat_json

DEFAULT_NEGATIVE = [
    "禁止编造认证标志、检测报告、参数数字、功效数字",
    "禁止乱码文字与无意义英文；文字信息只预留版面区域",
]

PROMPT_TEMPLATE = """请作为资深电商视觉设计总监，基于以下运营分析，产出设计方向 brief（生图执行依据）。

【目标人群】{audience}（痛点：{pain}）
【使用场景】{scenes}
【必须打穿的 Top3 卖点（主图核心，不得稀释）】
{top3}

请严格只输出 JSON：
{{
  "style": "整体风格定位（如：日系治愈/高级极简/强促销冲击，一句话理由含在内）",
  "color_direction": {{"primary": "主色", "accent": "点缀色", "tone": "色调情绪"}},
  "composition": ["构图语言1", "构图语言2", "构图语言3"],
  "keywords": ["生图风格关键词"],
  "negative": ["负面约束（至少包含禁止编造认证/参数/乱码）"],
  "screen_prompts": [
    {{"screen": 1, "name": "首屏定位", "prompt": "完整生图提示词（必须体现 Top3 卖点中的至少一个，含构图与色彩）"}}
  ]
}}

要求：
- screen_prompts 覆盖 8 屏（首屏定位/真实痛点/核心方案/场景代入/细节证明/使用门槛/类目化信任/决策收口）
- 每条 prompt 200 字内，产品锚点描述保持全组一致
- 风格必须贴合人群画像与痛点（治愈风贴合情绪痛点，对比风贴合功能痛点）"""


def build_prompt(profile: dict, table: dict) -> str:
    top3 = table.get("top3", [])
    top3_text = "\n".join(
        f"{i+1}. {t.get('point','')}（痛点：{t.get('pain','')}，位置：{t.get('surface','')}，score {t.get('score','')}）"
        for i, t in enumerate(top3)) or "（未提供，按风格通用处理）"
    return PROMPT_TEMPLATE.format(
        audience=profile.get("audience", {}).get("identity", "（未知）"),
        pain=profile.get("audience", {}).get("pain", "（未知）"),
        scenes="、".join(profile.get("scenes", [])) or "（无）",
        top3=top3_text,
    )


def normalize_brief(pid: str, raw: dict) -> dict:
    color = raw.get("color_direction") or {}
    if not isinstance(color, dict):
        color = {}
    comp = raw.get("composition") or []
    if isinstance(comp, str):
        comp = [comp]
    kws = raw.get("keywords") or []
    if isinstance(kws, str):
        kws = [kws]
    neg = [str(n) for n in (raw.get("negative") or []) if str(n).strip()]
    # 统一负面约束兜底（红线：防编造）
    neg_joined = " ".join(neg)
    for d in DEFAULT_NEGATIVE:
        if any(k in d for k in ("认证", "乱码")) and not any(k in neg_joined for k in ("认证", "乱码")):
            neg.append(d)

    screens = []
    for s in raw.get("screen_prompts") or []:
        if isinstance(s, dict) and s.get("prompt"):
            try:
                no = int(s.get("screen") or 0)
            except (TypeError, ValueError):
                no = 0
            screens.append({"screen": no, "name": str(s.get("name", "") or ""),
                            "prompt": str(s["prompt"])})

    style = str(raw.get("style", "") or "")
    return {
        "product_id": pid,
        "style": style,
        "color_direction": {
            "primary": str(color.get("primary", "") or ""),
            "accent": str(color.get("accent", "") or ""),
            "tone": str(color.get("tone", "") or ""),
        },
        "composition": [str(c) for c in comp][:5],
        "keywords": [str(k) for k in kws][:10],
        "negative": neg,
        "screen_prompts": screens[:8],
        "degraded": not (style and screens),
    }


async def analyze(profile: dict, table: dict,
                  cfg: AnalyzerConfig | None = None, out_dir: Path | None = None) -> dict:
    """产出 design_brief_{pid}.json。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    pid = profile.get("product_id", "?")
    raw = await chat_json(cfg, build_prompt(profile, table))
    b = normalize_brief(pid, raw)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / f"design_brief_{pid}.json"
        f.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
    return b
