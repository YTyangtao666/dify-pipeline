"""gpt-image-2 (apimart) 异步任务模式接入：提交→轮询→取图落盘。"""
import pytest

from scripts.pipeline import imagegen


def _cfg(tmp_path, **kw):
    from scripts.pipeline.config import Config
    defaults = dict(
        base_url="https://api.apimart.ai/v1", api_key="sk-test",
        image_model="gpt-image-2", proxy=None, out_dir=tmp_path,
        vlm_model="test-vlm", llm_model="test-llm")
    defaults.update(kw)
    return Config(**defaults)


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.content = payload if isinstance(payload, bytes) else str(payload).encode()

    def json(self):
        return self._p

    @property
    def text(self):
        return str(self._p)

    def raise_for_status(self):
        assert self.status_code < 400, self.status_code


class _FakeClient:
    """按脚本回放：POST 提交 → GET 轮询×2 → GET 下载图片。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self.script.pop(0)

    async def get(self, url):
        self.calls.append(("GET", url, None))
        return self.script.pop(0)

    async def aclose(self):
        pass


def test_apimart_submit_poll_download(tmp_path, monkeypatch):
    monkeypatch.setattr(imagegen, "throttle", lambda *a: _noop())
    submit = _Resp(200, {"code": 200, "data": [{"task_id": "task_X", "status": "submitted"}]})
    polling = _Resp(200, {"code": 200, "data": {"id": "task_X", "status": "processing", "progress": 10}})
    done = _Resp(200, {"code": 200, "data": {"id": "task_X", "status": "completed",
                                             "result": {"images": [{"url": ["http://x/1.png"]}]}}})
    img = _Resp(200, b"PNGDATA")
    fc = _FakeClient([submit, polling, done, img])

    r = _run_async(imagegen.generate_image(_cfg(tmp_path), "测试提示词", tmp_path / "a.png",
                                           client=fc, poll_interval=0))
    assert r.path.read_bytes() == b"PNGDATA"
    assert r.remote_url == "http://x/1.png"
    # 调用序列校验：提交→轮询→轮询→下载
    kinds = [c[0] for c in fc.calls]
    assert kinds == ["POST", "GET", "GET", "GET"]
    assert fc.calls[0][1] == "/images/generations"
    assert fc.calls[1][1] == "/tasks/task_X"
    assert fc.calls[3][1] == "http://x/1.png"


def test_apimart_task_failed_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(imagegen, "throttle", lambda *a: _noop())
    submit = _Resp(200, {"code": 200, "data": [{"task_id": "task_F", "status": "submitted"}]})
    failed = _Resp(200, {"code": 200, "data": {"id": "task_F", "status": "failed",
                                               "error": {"message": "content policy"}}})
    fc = _FakeClient([submit, failed])
    with pytest.raises(RuntimeError, match="content policy"):
        _run_async(imagegen.generate_image(_cfg(tmp_path), "违规词", tmp_path / "b.png",
                                           client=fc, poll_interval=0))


def test_apimart_sync_response_still_works(tmp_path, monkeypatch):
    """旧中转站同步 url 返回不能坏——双协议兼容。"""
    monkeypatch.setattr(imagegen, "throttle", lambda *a: _noop())
    sync = _Resp(200, {"data": [{"url": "http://x/old.png"}]})
    img = _Resp(200, b"OLD")
    fc = _FakeClient([sync, img])
    r = _run_async(imagegen.generate_image(_cfg(tmp_path), "p", tmp_path / "c.png", client=fc))
    assert r.path.read_bytes() == b"OLD"
    assert [c[0] for c in fc.calls] == ["POST", "GET"]


async def _noop():
    return None


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)
