"""analyzer.llm 测试：DeepSeek 官方客户端（重试/JSON提取/配置）"""
import json

import httpx
import pytest
import respx

from scripts.pipeline.analyzer.llm import AnalyzerConfig, chat_json

BASE = "https://api.deepseek.test/v1"


def make_cfg(tmp_path, **kw):
    return AnalyzerConfig(
        base_url=kw.get("base_url", BASE),
        api_key=kw.get("api_key", "sk-t"),
        model=kw.get("model", "deepseek-v4-flash"),
        proxy=kw.get("proxy"),
    )


class TestConfig:
    def test_reads_analyzer_env(self, monkeypatch):
        monkeypatch.setenv("ANALYZER_BASE_URL", "https://api.deepseek.com/v1")
        monkeypatch.setenv("ANALYZER_API_KEY", "sk-x")
        monkeypatch.setenv("ANALYZER_MODEL", "deepseek-v4-flash")
        cfg = AnalyzerConfig.from_env()
        assert cfg.base_url == "https://api.deepseek.com/v1"
        assert cfg.api_key == "sk-x"
        assert cfg.proxy is None  # DeepSeek 国内直连

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANALYZER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ANALYZER_API_KEY"):
            AnalyzerConfig.from_env()


class TestChatJson:
    async def test_parses_plain_json(self, tmp_path, monkeypatch):
        cfg = make_cfg(tmp_path)
        monkeypatch.setattr("scripts.pipeline.analyzer.llm._sleep", _no_sleep)
        payload = {"audience": "上班族", "scenes": ["办公室"], "selling_points": ["保温24h"]}
        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}))
            result = await chat_json(cfg, "分析这个产品")
        assert result == payload

    async def test_parses_fenced_json(self, tmp_path, monkeypatch):
        cfg = make_cfg(tmp_path)
        monkeypatch.setattr("scripts.pipeline.analyzer.llm._sleep", _no_sleep)
        payload = {"ok": True}
        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": f"```json\n{json.dumps(payload)}\n```"}}]}))
            result = await chat_json(cfg, "p")
        assert result == payload

    async def test_retries_on_429_then_succeeds(self, tmp_path, monkeypatch):
        cfg = make_cfg(tmp_path)
        monkeypatch.setattr("scripts.pipeline.analyzer.llm._sleep", _no_sleep)
        calls = {"n": 0}

        def flaky(request):
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(429, json={"e": 1})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"ok": 1}'}}]})

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(side_effect=flaky)
            result = await chat_json(cfg, "p")
        assert calls["n"] == 2 and result == {"ok": 1}

    async def test_unparsable_retries_then_raises(self, tmp_path, monkeypatch):
        cfg = make_cfg(tmp_path)
        monkeypatch.setattr("scripts.pipeline.analyzer.llm._sleep", _no_sleep)
        calls = {"n": 0}

        def gibberish(request):
            calls["n"] += 1
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "我认为这个产品很不错。"}}]})

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(side_effect=gibberish)
            with pytest.raises(RuntimeError, match="分析 LLM 调用失败"):
                await chat_json(cfg, "p")
        assert calls["n"] == 4  # RETRY_MAX+1 次尝试


async def _no_sleep(s):
    return None
