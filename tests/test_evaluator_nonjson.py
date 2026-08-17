"""VLM 响应 200 但 body 非 JSON（空/HTML 网关页）时不得崩溃，按重试/兜底处理。"""
import pytest

from scripts.pipeline import evaluator


class _Resp:
    status_code = 200

    def __init__(self, body):
        self.text = body

    def json(self):
        import json
        return json.loads(self.text)


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)

    async def post(self, url, json=None):
        return self.responses.pop(0)

    async def aclose(self):
        pass


def test_nonjson_200_body_raises_runtimeerror_not_jsonerror(tmp_path, monkeypatch):
    """200+空body 应该走到 RuntimeError(可重试语义)，而不是裸 JSONDecodeError 冒泡。"""
    import asyncio
    import base64
    from scripts.pipeline.config import Config
    img = tmp_path / "tiny.png"
    img.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
        "z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="))
    cfg = Config(base_url="https://x/v1", api_key="k", image_model="m",
                 vlm_model="vm", llm_model="lm", out_dir=tmp_path)
    client = _Client([_Resp("")] * 4)  # 4次全空body(重试3+1)
    monkeypatch.setattr(asyncio, "sleep", lambda *a: _nowait())
    _ = img  # 供 _evaluate_with 读取


async def _nowait():
    return None


def test_nonjson_body_message_contains_hint(tmp_path):
    with pytest.raises(RuntimeError, match="VLM 评分失败"):
        import asyncio
        import base64
        from pathlib import Path
        from scripts.pipeline.config import Config
        img = tmp_path / "tiny.png"
        # 1x1 红色 png（合法文件即可，请求会被 fake 拦截）
        img.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
            "z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="))
        cfg = Config(base_url="https://x/v1", api_key="k", image_model="m",
                     vlm_model="vm", llm_model="lm", out_dir=tmp_path)
        client = _Client([_Resp("<html>bad gateway</html>")] * 4)
        asyncio.run(evaluator._evaluate_with(
            cfg, img, "t",
            base_url="https://x/v1", api_key="k", model="vm",
            proxy=None, client=client))


def test_eval_payload_has_stream_false_and_big_max_tokens(tmp_path):
    """apimart 网关: 默认SSE; gemini-3.5-flash: 800 tokens 会截断 JSON。payload 必须显式 stream=false + max_tokens>=2000。"""
    import inspect
    from scripts.pipeline import evaluator as ev
    src_text = inspect.getsource(ev)
    assert '"stream": False' in src_text
    assert '"max_tokens": 2000' in src_text
