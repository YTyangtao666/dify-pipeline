"""L11 反馈迭代：LLM 四假设归因 → 框架库 score 回流 → 越用越准。

方法论（十一层·第十一层）：让 AI 归因（卖点错了/人群错了/视觉风格错了/信任感不够），
结论回到框架库——对的留下，错的删掉。今天做一张图明天重新开始，永远只是在用工具；
每次把数据回流给 AI，才是在训练自己的电商视觉系统。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..analyzer.framework import FrameworkLibrary
from ..analyzer.llm import AnalyzerConfig, chat_json

PROMPT_TEMPLATE = """请作为电商投放优化专家，基于 A/B 测试数据归因，产出可执行的迭代结论。

【投放数据（已按 CTR 降序）】
{results}

【本次使用的视觉方案】
风格：{style}
逐屏设计：
{screens}

【本次主打的 Top3 卖点】
{top3}

请严格只输出 JSON：
{{
  "winners": [
    {{"image": "图名", "why": "为什么赢（对应哪个卖点/哪种构图打穿了哪个痛点）", "keep": true}}
  ],
  "losers": [
    {{"image": "图名", "why": "为什么输", "fix": "下一版具体怎么改（构图/卖点/文案位置）"}}
  ],
  "hypothesis": {{
    "selling_point": true/false,   // 输因卖点选错（打的不是买家在意的）
    "audience": true/false,        // 输因人群错位（风格与画像不匹配）
    "style": true/false,           // 输因视觉风格（好看但不适合该平台/类目）
    "trust": true/false            // 输因信任感不足（材质/参数证据没打消顾虑）
  }},
  "framework_updates": [
    {{"framework_id": "fw_8screen_v1", "win": true/false, "evidence": "一句话数据证据"}}
  ]
}}

要求：
- hypothesis 至少一项为 true，且必须引用数据（CTR/CVR 差值）佐证
- fix 必须具体到可执行（「换个构图」不合格，「首屏从产品英雄图改为痛点对比图」合格）
- framework_updates 的 win：整体方案数据达标（如最佳图 CTR 高于均值 50%+）为 true"""


def build_prompt(results: dict, brief: dict, table: dict) -> str:
    rows = results.get("rows", [])
    rows_text = "\n".join(
        f"- {r['image']}: 曝光{r.get('impressions',0)} CTR {r.get('ctr',0):.2%} "
        f"CVR {r.get('cvr',0):.2%} 加购率 {r.get('cart_rate',0):.2%} "
        f"订单{r.get('orders',0)}"
        for r in rows[:12]) or "（无数据）"
    screens = brief.get("screen_prompts", [])
    screens_text = "\n".join(
        f"- 第{s.get('screen','?')}屏 {s.get('name','')}: {s.get('prompt','')[:60]}"
        for s in screens) or "（未提供）"
    top3 = table.get("top3", [])
    top3_text = "\n".join(
        f"{i+1}. {t.get('point','')}（痛点：{t.get('pain','')}）"
        for i, t in enumerate(top3)) or "（未提供）"
    return PROMPT_TEMPLATE.format(
        results=rows_text,
        style=brief.get("style", "（未知）"),
        screens=screens_text,
        top3=top3_text,
    )


TRUE_WORDS = {"true", "是", "yes", "1", "对"}
FALSE_WORDS = {"false", "否", "no", "0", "错"}


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in TRUE_WORDS


def normalize_verdict(pid: str, raw: dict) -> dict:
    winners = [w for w in (raw.get("winners") or [])
               if isinstance(w, dict) and str(w.get("image", "")).strip()]
    losers = [w for w in (raw.get("losers") or [])
              if isinstance(w, dict) and str(w.get("image", "")).strip()]
    hyp_raw = raw.get("hypothesis") or {}
    hyp = {k: _as_bool(hyp_raw.get(k, False))
           for k in ("selling_point", "audience", "style", "trust")}
    updates = []
    for u in raw.get("framework_updates") or []:
        if isinstance(u, dict) and u.get("framework_id"):
            updates.append({"framework_id": str(u["framework_id"]),
                            "win": _as_bool(u.get("win")),
                            "evidence": str(u.get("evidence", "") or "")})
    meaningful = winners or losers or updates
    return {
        "product_id": pid,
        "winners": [{"image": w["image"], "why": str(w.get("why", "") or ""),
                     "keep": _as_bool(w.get("keep", True))} for w in winners],
        "losers": [{"image": w["image"], "why": str(w.get("why", "") or ""),
                    "fix": str(w.get("fix", "") or "")} for w in losers],
        "hypothesis": hyp,
        "framework_updates": updates,
        "degraded": not meaningful,
        "created": datetime.now(timezone.utc).isoformat(),
    }


def apply_to_frameworks(verdict: dict, lib: FrameworkLibrary) -> int:
    """把归因结论回流框架库。红线2：score 只经 lib.update_score 修改。"""
    applied = 0
    for u in verdict.get("framework_updates", []):
        try:
            lib.update_score(u["framework_id"], win=u["win"])
            applied += 1
        except KeyError:
            continue  # 未知框架跳过
    lib.retire_if_stale()
    return applied


async def iterate(results: dict, brief: dict, table: dict,
                  lib: FrameworkLibrary | None = None,
                  cfg: AnalyzerConfig | None = None,
                  out_dir: Path | None = None) -> dict:
    """完整迭代：归因 → 回流框架库 → 落盘 iteration_{pid}.json。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    pid = results.get("product_id", "?")
    raw = await chat_json(cfg, build_prompt(results, brief, table))
    verdict = normalize_verdict(pid, raw)

    if lib is None:
        lib = FrameworkLibrary(Path("data/frameworks.json"))
    verdict["frameworks_applied"] = apply_to_frameworks(verdict, lib)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"iteration_{pid}.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    return verdict
