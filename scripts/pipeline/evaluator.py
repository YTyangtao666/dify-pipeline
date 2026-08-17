"""03 评分：VLM 逐图判定可用性，聚合 usable_rate / top_issue 报告。"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import Config

RETRY_MAX = 3
BACKOFF_BASE = 2.0

EVAL_PROMPT = """你是电商图片质检员。评估这张商品图是否能直接用于电商上架/投放。
商品：{title}
{top3_block}
判定维度：主体是否清晰完整、有无文字乱码/伪影、构图是否合格、是否美观可商用。
{top3_rule}严格只输出 JSON（不要多余文字）：
{{"usable": true/false, "score": 0-100, "issues": [{{"type": "问题类型", "note": "一句话说明"}}]{top3_json}}}
无问题则 issues 为空数组。"""


def build_eval_prompt(title: str, top3_table: dict | None = None) -> str:
    """构造质检 prompt。有卖点表时升级为「打穿 Top3」标准（方法论 L9×L7 联动）。"""
    if top3_table and top3_table.get("top3"):
        lines = []
        for t in top3_table["top3"]:
            lines.append(f"- {t.get('point','')}（对应痛点：{t.get('pain','')}）")
        top3_block = "【本组图必须打穿的 Top3 卖点】\n" + "\n".join(lines)
        top3_rule = "额外判定：每条 Top3 卖点是否在这张图里被清晰传达（视觉可见，不是文字堆砌）。\n"
        top3_json = ', "top3_hits": [{"point": "卖点", "hit": true/false}]'
    else:
        top3_block = ""
        top3_rule = ""
        top3_json = ""
    return EVAL_PROMPT.format(title=title, top3_block=top3_block,
                              top3_rule=top3_rule, top3_json=top3_json)


@dataclass
class Verdict:
    usable: bool
    score: int
    issues: list = field(default_factory=list)
    parse_ok: bool = True
    image: str = ""
    top3_hits: list = field(default_factory=list)  # [{point, hit}] L7 联动质检


def strip_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    return text.rstrip("`").strip()


def extract_json(text: str) -> dict | None:
    """从 VLM 输出中提取第一个平衡 JSON 对象。"""
    cleaned = strip_fences(text)
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            start = i
            break
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if escaped:
            escaped = False
            continue
        if c == "\\":
            escaped = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def evaluate_image(cfg: Config, image_path: Path, product_title: str,
                         client: httpx.AsyncClient | None = None,
                         top3_table: dict | None = None) -> Verdict:
    """单图 VLM 评分。返回 Verdict；解析失败视为不可用。

    主端点 403 配额耗尽（insufficient_quota）时立即切换兜底端点（不烧重试时间）。
    top3_table 提供时升级为「打穿 Top3」质检标准。
    cfg.eval_votes > 1 时多票表决（hit 多数决 / score 中位数），抗概率性输出。
    """
    votes_n = max(1, getattr(cfg, "eval_votes", 1))
    verdicts: list[Verdict] = []
    for _ in range(votes_n):
        v = await _evaluate_one(cfg, image_path, product_title,
                                client=client, top3_table=top3_table)
        verdicts.append(v)
    return _merge_verdicts(verdicts, image_path.name)


async def _evaluate_one(cfg: Config, image_path: Path, product_title: str,
                        client: httpx.AsyncClient | None = None,
                        top3_table: dict | None = None) -> Verdict:
    """单次完整评分（主端点 → 配额切换兜底）。"""
    verdict = await _evaluate_with(cfg, image_path, product_title,
                                   base_url=cfg.base_url, api_key=cfg.api_key,
                                   model=cfg.vlm_model, proxy=cfg.proxy,
                                   client=client, top3_table=top3_table)
    if verdict is not None:
        return verdict
    if cfg.vlm_fallback_url and cfg.vlm_fallback_key:
        print("  [VLM] 主端点配额耗尽 → 切换兜底端点")
        verdict = await _evaluate_with(cfg, image_path, product_title,
                                       base_url=cfg.vlm_fallback_url,
                                       api_key=cfg.vlm_fallback_key,
                                       model=cfg.vlm_fallback_model or cfg.vlm_model,
                                       proxy=cfg.vlm_fallback_proxy, top3_table=top3_table)
        if verdict is not None:
            return verdict
        raise RuntimeError(f"VLM 评分失败（主+兜底均不可用）")
    raise RuntimeError(f"VLM 评分失败（重试{RETRY_MAX}次后）: 配额耗尽且未配置兜底端点")


def _merge_verdicts(vs: list[Verdict], image_name: str) -> Verdict:
    """多票合并：usable/score 中位、hit 多数决、issues 并集去重。"""
    if len(vs) == 1:
        vs[0].image = image_name
        return vs[0]
    scores = sorted(v.score for v in vs)
    mid = scores[len(scores) // 2] if len(scores) % 2 else (scores[len(scores)//2 - 1] + scores[len(scores)//2]) / 2
    usable = sum(1 for v in vs if v.usable) * 2 > len(vs)
    issues_seen: dict[str, dict] = {}
    for v in vs:
        for iss in v.issues:
            t = str(iss.get("type") or "其他")
            if t not in ("无", ""):
                issues_seen.setdefault(t, iss)
    # top3_hits 多数决（按 point 对齐）
    points_order: list[str] = []
    for v in vs:
        for h in v.top3_hits or []:
            p = str(h.get("point", "")).strip()
            if p and p not in points_order:
                points_order.append(p)
    merged_hits = []
    for p in points_order:
        trues = 0
        total = 0
        for v in vs:
            for h in v.top3_hits or []:
                if str(h.get("point", "")).strip() == p:
                    total += 1
                    if h.get("hit"):
                        trues += 1
        if total:
            merged_hits.append({"point": p, "hit": trues * 2 > total})
    return Verdict(
        usable=usable,
        score=int(round(mid)),
        issues=list(issues_seen.values()),
        parse_ok=all(v.parse_ok for v in vs),
        image=image_name,
        top3_hits=merged_hits,
    )


async def _evaluate_with(cfg: Config, image_path: Path, product_title: str, *,
                         base_url: str, api_key: str, model: str, proxy: str | None,
                         client: httpx.AsyncClient | None = None,
                         top3_table: dict | None = None) -> Verdict | None:
    """在指定端点上评分。配额类 403 返回 None（触发上层切换）；其他错误按重试语义。"""
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    eval_prompt = build_eval_prompt(product_title, top3_table=top3_table)
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": eval_prompt},
            ],
        }],
        "max_tokens": 800,
    }

    own = False
    if client is None or _client_mismatch(client, base_url, api_key):
        client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            proxy=proxy, timeout=120.0,
        )
        own = True
    assert client is not None

    last_err = None
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code == 403 and "quota" in resp.text.lower():
                if own:
                    await client.aclose()
                return None  # 配额耗尽：交上层切换
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"].get("content") or ""
                data = extract_json(content)
                if data is None:
                    last_err = "unparsable VLM output"
                    if attempt < RETRY_MAX:
                        await asyncio.sleep(BACKOFF_BASE ** (attempt + 1))
                        continue
                    v = Verdict(usable=False, score=0, parse_ok=False,
                                image=image_path.name)
                    if own:
                        await client.aclose()
                    return v
                v = Verdict(
                    usable=bool(data.get("usable")),
                    score=int(data.get("score") or 0),
                    issues=list(data.get("issues") or []),
                    image=image_path.name,
                    top3_hits=list(data.get("top3_hits") or []),
                )
                if own:
                    await client.aclose()
                return v
            last_err = f"HTTP {resp.status_code}"
        except httpx.HTTPError as e:
            last_err = str(e)[:200]
        if attempt < RETRY_MAX:
            await asyncio.sleep(BACKOFF_BASE ** (attempt + 1))

    if own:
        await client.aclose()
    raise RuntimeError(f"VLM 评分失败（重试{RETRY_MAX}次后）: {last_err}")


def _client_mismatch(client: httpx.AsyncClient, base_url: str, api_key: str) -> bool:
    """注入的 client 是否指向目标端点（兜底时主 client 不可复用）。"""
    try:
        return str(client.base_url).rstrip("/") != base_url.rstrip("/")
    except Exception:  # noqa: BLE001
        return True


def build_report(verdicts: list[Verdict]) -> dict:
    """聚合：usable_rate(%) + top_issue + Top3 打穿覆盖率 + 明细。"""
    total = len(verdicts)
    if total == 0:
        return {"total": 0, "usable": 0, "usable_rate": 0.0, "top_issue": "",
                "top3_coverage": {}, "items": []}
    usable = sum(1 for v in verdicts if v.usable)
    counter: dict[str, int] = {}
    for v in verdicts:
        for iss in v.issues:
            t = str(iss.get("type") or "其他")
            counter[t] = counter.get(t, 0) + 1
    top_issue = max(counter, key=counter.get) if counter else ""
    # Top3 打穿覆盖率：每条卖点被几张图清晰传达
    coverage: dict[str, int] = {}
    for v in verdicts:
        for h in v.top3_hits or []:
            if isinstance(h, dict) and h.get("hit"):
                p = str(h.get("point", "")).strip()
                if p:
                    coverage[p] = coverage.get(p, 0) + 1
    return {
        "total": total,
        "usable": usable,
        "usable_rate": round(usable / total * 100, 1),
        "top_issue": top_issue,
        "issue_counts": counter,
        "top3_coverage": coverage,
        "items": [
            {"image": v.image, "usable": v.usable, "score": v.score,
             "issues": v.issues, "parse_ok": v.parse_ok,
             "top3_hits": v.top3_hits}
            for v in verdicts
        ],
    }


def coverage_pct(overall: dict) -> float | None:
    """Top3 打穿率：hit 数 / Top3 判定总数。无 Top3 数据返回 None（styles 模式不卡）。"""
    total = sum(len(it.get("top3_hits") or []) for it in overall.get("items", []))
    if total == 0:
        return None
    hits = sum(1 for it in overall.get("items", [])
               for h in (it.get("top3_hits") or [])
               if isinstance(h, dict) and h.get("hit"))
    return round(hits / total * 100, 2)
