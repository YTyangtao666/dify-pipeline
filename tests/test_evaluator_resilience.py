"""evaluator 韧性测试：VLM 网络失败不应直接判死为 score=0"""
import httpx
import pytest
import respx

from scripts.pipeline.config import Config

BASE = "https://yunwu.test/v1"


def make_config(tmp_path):
    return Config(base_url=BASE, api_key="sk-t", image_model="m",
                  vlm_model="vlm", llm_model="llm", out_dir=tmp_path)


class TestVlmResilience:
    async def test_transient_503_exhausts_retries_then_raises(self, tmp_path, monkeypatch):
        """连续 5xx 超过重试上限 → 抛异常（由上层 03 脚本捕获记 failed），不返回假 0 分"""
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(
                return_value=httpx.Response(503, json={"e": 1}))
            with pytest.raises(RuntimeError, match="VLM 评分失败"):
                await evaluator.evaluate_image(cfg, img, "保温杯")

    async def test_retry_then_success_after_two_503(self, tmp_path, monkeypatch):
        """两次 503 后第三次成功 → 正常返回判定（网络抖动被重试吸收）"""
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        calls = {"n": 0}

        def flaky(request):
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(503, json={"e": 1})
            return httpx.Response(200, json={"choices": [
                {"message": {"content": '{"usable": true, "score": 92, "issues": []}'}}]})

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(side_effect=flaky)
            v = await evaluator.evaluate_image(cfg, img, "保温杯")

        assert calls["n"] == 3
        assert v.usable is True and v.score == 92

    async def test_unparsable_output_retries_then_gives_verdict(self, tmp_path, monkeypatch):
        """VLM 输出无法解析 → 应先重试；重试耗尽后返回 parse_ok=False 的判定（保留现有语义）"""
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        calls = {"n": 0}

        def gibberish(request):
            calls["n"] += 1
            return httpx.Response(200, json={"choices": [
                {"message": {"content": "这张图很好看！"}}]})

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(side_effect=gibberish)
            v = await evaluator.evaluate_image(cfg, img, "保温杯")

        # 解析失败也应重试满（RETRY_MAX+1=4 次尝试）再放弃
        assert calls["n"] == 4
        assert v.usable is False and v.parse_ok is False


async def _no_sleep(s):
    return None
