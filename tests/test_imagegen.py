"""imagegen 模块测试：重试、b64/url 双兼容、限速、代理"""
import base64
import json

import httpx
import pytest
import respx

from scripts.pipeline.config import Config

BASE = "https://yunwu.test/v1"


def make_config(tmp_path, **kw):
    defaults = dict(
        base_url=BASE, api_key="sk-test", image_model="qwen-image",
        vlm_model="vlm", llm_model="llm", out_dir=tmp_path,
    )
    defaults.update(kw)
    return Config(**defaults)


class TestGenerateImage:
    async def test_returns_url_result_and_client_downloads(self, tmp_path):
        """中转站返回 url → 结果记录 url 且图片已下载到本地"""
        from scripts.pipeline import imagegen

        cfg = make_config(tmp_path)
        png = base64.b64encode(b"\x89PNG-fake-bytes").decode()

        def serve_img(request):
            return httpx.Response(200, content=b"\x89PNG-fake-bytes")

        with respx.mock(base_url=BASE) as mock:
            mock.post("/images/generations").mock(
                return_value=httpx.Response(200, json={
                    "data": [{"url": f"{BASE}/files/a.png"}]
                })
            )
            mock.get("/files/a.png").mock(side_effect=serve_img)
            result = await imagegen.generate_image(cfg, "a red apple", tmp_path / "a.png")

        assert result.path == tmp_path / "a.png"
        assert result.path.read_bytes() == b"\x89PNG-fake-bytes"

    async def test_returns_b64_result(self, tmp_path):
        """中转站返回 b64_json → 直接落盘"""
        from scripts.pipeline import imagegen

        cfg = make_config(tmp_path)
        raw = b"\x89PNG-fake-2"
        b64 = base64.b64encode(raw).decode()
        with respx.mock(base_url=BASE) as mock:
            mock.post("/images/generations").mock(
                return_value=httpx.Response(200, json={"data": [{"b64_json": b64}]})
            )
            result = await imagegen.generate_image(cfg, "a red apple", tmp_path / "b.png")

        assert result.path.read_bytes() == raw

    async def test_retries_3_times_with_backoff_then_succeeds(self, tmp_path, monkeypatch):
        """429 限流 → 3 次重试后成功（指数退避加速）"""
        from scripts.pipeline import imagegen

        cfg = make_config(tmp_path)
        calls = {"n": 0}
        sleeps = []

        async def fake_sleep(s):
            sleeps.append(s)

        monkeypatch.setattr(imagegen.asyncio, "sleep", fake_sleep)

        def flaky(request):
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, json={"error": "rate"})
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"ok3").decode()}]})

        with respx.mock(base_url=BASE) as mock:
            mock.post("/images/generations").mock(side_effect=flaky)
            result = await imagegen.generate_image(cfg, "p", tmp_path / "c.png")

        assert calls["n"] == 3
        assert result.path.read_bytes() == b"ok3"
        assert sleeps == [2, 4]  # 指数退避 2s,4s

    async def test_fails_after_max_retries(self, tmp_path, monkeypatch):
        """连续 429 超过重试上限 → 抛异常"""
        from scripts.pipeline import imagegen

        cfg = make_config(tmp_path)
        monkeypatch.setattr(imagegen.asyncio, "sleep", _no_sleep)

        with respx.mock(base_url=BASE) as mock:
            mock.post("/images/generations").mock(
                return_value=httpx.Response(429, json={"error": "rate"})
            )
            with pytest.raises(RuntimeError, match="生图失败"):
                await imagegen.generate_image(cfg, "p", tmp_path / "d.png")

    async def test_request_interval_throttle(self, tmp_path, monkeypatch):
        """每次生图请求之间有节流间隔（默认1s，可注入）"""
        from scripts.pipeline import imagegen

        cfg = make_config(tmp_path)
        sleeps = []

        async def fake_sleep(s):
            sleeps.append(s)

        monkeypatch.setattr(imagegen.asyncio, "sleep", fake_sleep)
        with respx.mock(base_url=BASE) as mock:
            mock.post("/images/generations").mock(
                return_value=httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"x").decode()}]})
            )
            await imagegen.generate_image(cfg, "p1", tmp_path / "1.png", interval=0.5)
            await imagegen.generate_image(cfg, "p2", tmp_path / "2.png", interval=0.5)

        # 第二次调用前应 sleep(interval)
        assert 0.5 in sleeps


@pytest.fixture(autouse=True)
def reset_throttle():
    """每个测试前重置模块级限速状态，避免跨测试污染。"""
    from scripts.pipeline import imagegen
    imagegen._last_request_ts = 0.0
    yield
    imagegen._last_request_ts = 0.0


async def _no_sleep(s):
    return None
