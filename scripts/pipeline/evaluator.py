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

判定维度：主体是否清晰完整、有无文字乱码/伪影、构图是否合格、是否美观可商用。
严格只输出 JSON（不要多余文字）：
{{"usable": true/false, "score": 0-100, "issues": [{{"type": "问题类型", "note": "一句话说明"}}]}}
无问题则 issues 为空数组。"""


@dataclass
class Verdict:
    usable: bool
    score: int
    issues: list = field(default_factory=list)
    parse_ok: bool = True
    image: str = ""


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
                         client: httpx.AsyncClient | None = None) -> Verdict:
    """单图 VLM 评分。返回 Verdict；解析失败视为不可用。"""
    own = client is None
    if own:
        client = httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            proxy=cfg.proxy, timeout=120.0,
        )
    assert client is not None

    b64 = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": cfg.vlm_model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": EVAL_PROMPT.format(title=product_title)},
            ],
        }],
        "max_tokens": 800,
    }

    last_err = None
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"].get("content") or ""
                data = extract_json(content)
                if data is None:
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
                )
                if own:
                    await client.aclose()
                return v
            last_err = f"HTTP {resp.status_code}"
        except (httpx.HTTPError, KeyError) as e:
            last_err = str(e)[:200]
        if attempt < RETRY_MAX:
            await asyncio.sleep(BACKOFF_BASE ** (attempt + 1))

    if own:
        await client.aclose()
    raise RuntimeError(f"VLM 评分失败（重试{RETRY_MAX}次后）: {last_err}")


def build_report(verdicts: list[Verdict]) -> dict:
    """聚合：usable_rate(%) + top_issue + 明细。"""
    total = len(verdicts)
    if total == 0:
        return {"total": 0, "usable": 0, "usable_rate": 0.0, "top_issue": "", "items": []}
    usable = sum(1 for v in verdicts if v.usable)
    counter: dict[str, int] = {}
    for v in verdicts:
        for iss in v.issues:
            t = str(iss.get("type") or "其他")
            counter[t] = counter.get(t, 0) + 1
    top_issue = max(counter, key=counter.get) if counter else ""
    return {
        "total": total,
        "usable": usable,
        "usable_rate": round(usable / total * 100, 1),
        "top_issue": top_issue,
        "issue_counts": counter,
        "items": [
            {"image": v.image, "usable": v.usable, "score": v.score,
             "issues": v.issues, "parse_ok": v.parse_ok}
            for v in verdicts
        ],
    }
