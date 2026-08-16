"""分析链 LLM 客户端：DeepSeek 官方（国内直连），复用 JSON 提取与重试模式。"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

import httpx

from ..evaluator import extract_json

RETRY_MAX = 3
BACKOFF_BASE = 2.0


async def _sleep(sec: float) -> None:
    await asyncio.sleep(sec)


@dataclass
class AnalyzerConfig:
    base_url: str
    api_key: str
    model: str
    proxy: str | None = None

    @classmethod
    def from_env(cls) -> "AnalyzerConfig":
        api_key = os.environ.get("ANALYZER_API_KEY")
        if not api_key:
            raise RuntimeError("ANALYZER_API_KEY 未设置：请在 .env 提供 DeepSeek 官方 key")
        return cls(
            base_url=os.environ.get("ANALYZER_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=api_key,
            model=os.environ.get("ANALYZER_MODEL", "deepseek-v4-flash"),
            proxy=os.environ.get("ANALYZER_PROXY") or None,
        )


def build_client(cfg: AnalyzerConfig, timeout: float = 120.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=cfg.base_url,
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        proxy=cfg.proxy,   # DeepSeek 国内直连，默认不走代理
        timeout=timeout,
    )


async def chat_json(cfg: AnalyzerConfig, prompt: str,
                    system: str = "你是资深电商运营专家。严格只输出 JSON，不要输出任何其他文字。",
                    max_tokens: int = 4000,
                    client: httpx.AsyncClient | None = None) -> dict:
    """调 LLM 并强制解析为 JSON dict。解析失败按网络故障同等重试。"""
    own = client is None
    if own:
        client = build_client(cfg)
    assert client is not None

    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    last_err = None
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"].get("content") or ""
                data = extract_json(content)
                if isinstance(data, dict):
                    if own:
                        await client.aclose()
                    return data
                last_err = "unparsable output"
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except httpx.HTTPError as e:
            last_err = str(e)[:200]
        if attempt < RETRY_MAX:
            await _sleep(BACKOFF_BASE ** (attempt + 1))

    if own:
        await client.aclose()
    raise RuntimeError(f"分析 LLM 调用失败（重试{RETRY_MAX}次后）: {last_err}")
