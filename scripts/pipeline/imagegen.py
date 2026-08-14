"""生图客户端：OpenAI 兼容 /images/generations，支持 b64/url 双返回、重试、限速、代理。"""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Config

RETRY_MAX = 3          # 最多重试 3 次（共 4 次机会里前 3 次失败才重试）
BACKOFF_BASE = 2.0     # 指数退避基数：2s, 4s, 8s


@dataclass
class GenResult:
    path: Path
    remote_url: str | None = None
    b64: bool = False


_last_request_ts: float = 0.0


def build_client(cfg: Config, timeout: float = 180.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=cfg.base_url,
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        proxy=cfg.proxy,
        timeout=timeout,
    )


async def generate_image(
    cfg: Config,
    prompt: str,
    out_path: Path,
    *,
    size: str = "1024x1024",
    interval: float = 1.0,
    client: httpx.AsyncClient | None = None,
) -> GenResult:
    """生成单张图并落盘。兼容 url / b64_json 两种返回。"""
    global _last_request_ts

    own = client is None
    if own:
        client = build_client(cfg)
    assert client is not None

    # 请求间隔节流：距上次请求不足 interval 则等待
    await throttle(interval)
    global _last_request_ts
    _last_request_ts = time.monotonic()

    payload = {"model": cfg.image_model, "prompt": prompt, "size": size, "n": 1}
    last_err = None
    for attempt in range(RETRY_MAX + 1):
        resp = await client.post("/images/generations", json=payload)
        if resp.status_code == 200:
            data = resp.json()["data"][0]
            return await _save(cfg, data, out_path, client)
        last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < RETRY_MAX:
            await asyncio.sleep(BACKOFF_BASE ** (attempt + 1))
            continue
        break

    if own:
        await client.aclose()
    raise RuntimeError(f"生图失败（重试{RETRY_MAX}次后）: {last_err}")


async def throttle(interval: float) -> None:
    """模块级限速：距上次生图请求不足 interval 秒则 sleep 补足。"""
    global _last_request_ts
    if _last_request_ts > 0:
        elapsed = time.monotonic() - _last_request_ts
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)


async def _save(cfg: Config, item: dict, out_path: Path, client: httpx.AsyncClient) -> GenResult:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
        return GenResult(path=out_path, b64=True)
    url = item.get("url")
    if url:
        dl = await client.get(url)
        dl.raise_for_status()
        out_path.write_bytes(dl.content)
        return GenResult(path=out_path, remote_url=url)
    raise RuntimeError(f"生图返回里既无 b64_json 也无 url: {str(item)[:200]}")
