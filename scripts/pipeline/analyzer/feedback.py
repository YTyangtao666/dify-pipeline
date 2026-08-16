"""L6 用户反馈：京东评论采集 + LLM 提炼痛点词云/高频问题/信任缺口。

方法论（十一层·第六层）：买家真正关心什么不在老板嘴里，在评论区里。
好评=认可理由，差评=最痛的点，问答=最关心的问题。
"""
from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from .llm import AnalyzerConfig, chat_json

MAX_COMMENTS_IN_PROMPT = 120
MAX_PROMPT_LEN = 28000

PROMPT_TEMPLATE = """请作为电商用户研究分析师，分析商品（ID: {pid}）的买家评论，提炼三份洞察（痛点词云、高频问题、信任缺口）。

【评论列表】
{comments}

请严格只输出 JSON：
{{
  "pain_words": [
    {{"word": "痛点词", "count": 频次整数, "sentiment": "neg/neutral/pos"}}
  ],
  "top_questions": ["买家最关心的问题（问句形式）"],
  "trust_gaps": ["信任缺口（买家担心但评论未打消的点）"]
}}

要求：
- pain_words 按频次降序，至少 5 个
- 差评与带犹豫语气的评论权重高于好评
- trust_gaps 是做图要补的信任证据（如材质/尺寸/售后）"""


def parse_jd_comments(html: str) -> list[str]:
    """解析京东评论页 HTML（Playwright 抓取后解析）。"""
    soup = BeautifulSoup(html, "lxml")
    comments = []
    for item in soup.select(".comment-item"):
        el = item.select_one(".comment-content") or item.select_one("p")
        text = (el.get_text(" ", strip=True) if el else "").strip()
        if text:
            comments.append(text)
    # 兜底：无标准结构时抓所有 p 文本
    if not comments:
        comments = [p.get_text(strip=True) for p in soup.select("p") if p.get_text(strip=True)]
    return comments


async def scrape_jd_comments(product_url_or_id: str, limit: int = 100) -> list[str]:
    """Playwright 抓取商品评论（真实网络，E2E 用）。"""
    from playwright.async_api import async_playwright

    if product_url_or_id.startswith("http"):
        url = product_url_or_id
    else:
        url = f"https://item.jd.com/{product_url_or_id}.html"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
        try:
            await page.goto(url + "#comment", wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(3000)
            html = await page.content()
        finally:
            await browser.close()
    return parse_jd_comments(html)[:limit]


def build_prompt(pid: str, comments: list[str]) -> str:
    shown = comments[:MAX_COMMENTS_IN_PROMPT]
    body = "\n".join(f"- {c}" for c in shown) or "（无评论）"
    prompt = PROMPT_TEMPLATE.format(pid=pid, comments=body)
    if len(prompt) > MAX_PROMPT_LEN:  # 防爆 token
        prompt = prompt[:MAX_PROMPT_LEN] + "\n…（截断）\n请只输出 JSON。"
    return prompt


def normalize_feedback(pid: str, raw: dict) -> dict:
    pain_words = []
    for w in raw.get("pain_words") or []:
        if isinstance(w, dict) and str(w.get("word", "")).strip():
            try:
                cnt = int(w.get("count") or 0)
            except (TypeError, ValueError):
                cnt = 0
            pain_words.append({"word": str(w["word"]).strip(), "count": cnt,
                               "sentiment": str(w.get("sentiment", "") or "")})
        elif isinstance(w, str) and w.strip():
            pain_words.append({"word": w.strip(), "count": 0, "sentiment": ""})
    pain_words.sort(key=lambda x: x["count"], reverse=True)

    questions = [str(q) for q in (raw.get("top_questions") or []) if str(q).strip()][:10]
    gaps = [str(g) for g in (raw.get("trust_gaps") or []) if str(g).strip()][:10]

    return {
        "product_id": pid,
        "pain_words": pain_words[:15],
        "top_questions": questions,
        "trust_gaps": gaps,
        "degraded": not (pain_words or questions or gaps),
    }


async def analyze(pid: str, comments: list[str] | None = None,
                  cfg: AnalyzerConfig | None = None, out_dir: Path | None = None) -> dict:
    """提炼买家反馈洞察并落盘 feedback_{pid}.json。comments 为空时自动采集。"""
    if cfg is None:
        cfg = AnalyzerConfig.from_env()
    if comments is None:
        try:
            comments = await scrape_jd_comments(pid)
        except Exception as e:  # noqa: BLE001
            comments = []
            print(f"[L6] ⚠️ 评论采集失败（{e}），用空评论降级分析")
    raw = await chat_json(cfg, build_prompt(pid, comments))
    f = normalize_feedback(pid, raw)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"feedback_{pid}.json").write_text(
            json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")
    return f
