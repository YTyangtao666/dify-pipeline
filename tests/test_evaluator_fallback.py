"""evaluator 双 VLM 端点测试：yunwu 主 + 智谱 glm-4v-flash 兜底"""
import base64
import json

import httpx
import pytest
import respx

from scripts.pipeline.config import Config

YUNWU = "https://yunwu.test/v1"
ZHIPU = "https://open.bigmodel.test/v4"


def make_cfg(tmp_path, **kw):
    return Config(base_url=YUNWU, api_key="sk-t", image_model="m",
                  vlm_model="gemini-3.5-flash", llm_model="llm", out_dir=tmp_path, **kw)


def vlm_ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class TestVlmFallback:
    async def test_zhipu_fallback_on_403_quota(self, tmp_path, monkeypatch):
        """yunwu 403 配额耗尽 → 自动切智谱端点成功"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path, vlm_fallback_url=ZHIPU, vlm_fallback_key="zp-k",
                       vlm_fallback_model="glm-4v-flash")
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())

        calls = {"yunwu": 0, "zhipu": 0}
        verdict = json.dumps({"usable": True, "score": 90, "issues": []})

        def yunwu_route(request):
            calls["yunwu"] += 1
            return httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}})

        def zhipu_route(request):
            calls["zhipu"] += 1
            return vlm_ok(verdict)

        with respx.mock(base_url=YUNWU) as m1, respx.mock(base_url=ZHIPU) as m2:
            m1.post("/chat/completions").mock(side_effect=yunwu_route)
            m2.post("/chat/completions").mock(side_effect=zhipu_route)
            v = await evaluator.evaluate_image(cfg, img, "保温杯")

        assert calls["yunwu"] == 1          # 403 立即切换，不重试烧时间
        assert calls["zhipu"] == 1
        assert v.usable is True and v.score == 90

    async def test_no_fallback_config_raises_immediately_on_quota(self, tmp_path, monkeypatch):
        """未配兜底 → 配额 403 立即失败（重试无意义，不再烧退避时间）"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path)  # 无 fallback
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())
        with respx.mock(base_url=YUNWU) as m:
            m.post("/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            with pytest.raises(RuntimeError, match="配额耗尽且未配置兜底"):
                await evaluator.evaluate_image(cfg, img, "保温杯")

    async def test_fallback_also_fails_raises(self, tmp_path, monkeypatch):
        """兜底也 403 配额 → 抛错"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path, vlm_fallback_url=ZHIPU, vlm_fallback_key="zp",
                       vlm_fallback_model="glm-4v-flash")
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())
        with respx.mock(assert_all_called=False) as m:
            m.post(f"{YUNWU}/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            m.post(f"{ZHIPU}/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            with pytest.raises(RuntimeError, match="VLM"):
                await evaluator.evaluate_image(cfg, img, "保温杯")


async def _no_sleep(s):
    return None
