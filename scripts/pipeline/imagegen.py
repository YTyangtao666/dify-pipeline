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
    poll_interval: float = 3.0,
    poll_timeout: float = 300.0,
) -> GenResult:
    """生成单张图并落盘。兼容三种返回：b64_json / url（同步）与 task_id（异步轮询）。"""
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
            body = resp.json()
            first = (body.get("data") or [{}])[0]
            task_id = first.get("task_id")
            if task_id:
                return await _poll_task(cfg, task_id, out_path, client,
                                        poll_interval, poll_timeout)
            return await _save(cfg, first, out_path, client)
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


POLL_TERMINAL = ("completed", "failed")


async def _poll_task(
    cfg: Config,
    task_id: str,
    out_path: Path,
    client: httpx.AsyncClient,
    poll_interval: float,
    poll_timeout: float,
) -> GenResult:
    """apimart 异步任务模式：GET /tasks/{id} 轮询到 completed → 取 images[0].url[0] 下载落盘。"""
    import asyncio as _aio

    t0 = time.monotonic()
    while True:
        resp = await client.get(f"/tasks/{task_id}")
        body = resp.json().get("data", {})
        status = body.get("status", "")
        if status == "completed":
            urls = body["result"]["images"][0]["url"]
            url = urls[0] if isinstance(urls, list) else urls
            dl = await client.get(url)
            dl.raise_for_status()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(dl.content)
            return GenResult(path=out_path, remote_url=url)
        if status == "failed":
            msg = (body.get("error") or {}).get("message", "unknown")
            raise RuntimeError(f"生图任务失败: {msg}")
        if time.monotonic() - t0 > poll_timeout:
            raise RuntimeError(f"生图任务轮询超时({poll_timeout}s): {task_id} status={status}")
        await _aio.sleep(poll_interval)
