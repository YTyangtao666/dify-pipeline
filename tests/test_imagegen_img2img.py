"""C1: 图生图——generate_image 支持参考图数组（白底图/模特图→新构图）。"""
from pathlib import Path

from scripts.pipeline import imagegen
from scripts.pipeline.config import Config


def _cfg(tmp_path):
    return Config(base_url="https://api.apimart.ai/v1", api_key="sk-t",
                  image_model="gpt-image-2", proxy=None, out_dir=tmp_path,
                  vlm_model="vm", llm_model="lm")


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
        assert self.status_code < 400


class _FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.captured = []

    async def post(self, url, json=None):
        self.captured.append(("POST", url, json))
        return self.script.pop(0)

    async def get(self, url):
        self.captured.append(("GET", url, None))
        return self.script.pop(0)

    async def aclose(self):
        pass


def _png_bytes() -> bytes:
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
        "z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")


def test_reference_images_forwarded_as_b64_data_urls(tmp_path):
    """本地参考图文件 → data URL 进 image_urls 字段（apimart 图生图协议）。"""
    import asyncio
    ref1 = tmp_path / "white.png"
    ref2 = tmp_path / "model.png"
    ref1.write_bytes(_png_bytes())
    ref2.write_bytes(_png_bytes())
    submit = _Resp(200, {"code": 200, "data": [{"task_id": "t1", "status": "submitted"}]})
    done = _Resp(200, {"code": 200, "data": {"id": "t1", "status": "completed",
                                             "result": {"images": [{"url": ["http://x/1.png"]}]}}})
    img = _Resp(200, b"NEW")
    fc = _FakeClient([submit, done, img])

    r = asyncio.run(imagegen.generate_image(
        _cfg(tmp_path), "把商品放进秋日咖啡馆场景", tmp_path / "out.png",
        client=fc, poll_interval=0, reference_images=[ref1, ref2]))

    assert r.path.read_bytes() == b"NEW"
    payload = fc.captured[0][2]
    # 两条 data URL、前缀正确
    urls = payload["image_urls"]
    assert len(urls) == 2
    assert all(u.startswith("data:image/png;base64,") for u in urls)
    import base64
    assert base64.b64decode(urls[0].split(",", 1)[1]) == _png_bytes()


def test_reference_images_passthrough_urls(tmp_path):
    """已经是 http(s) URL 的参考图直接透传，不转 base64。"""
    import asyncio
    submit = _Resp(200, {"code": 200, "data": [{"task_id": "t2", "status": "submitted"}]})
    done = _Resp(200, {"code": 200, "data": {"id": "t2", "status": "completed",
                                             "result": {"images": [{"url": ["http://x/2.png"]}]}}})
    img = _Resp(200, b"OK2")
    fc = _FakeClient([submit, done, img])
    asyncio.run(imagegen.generate_image(
        _cfg(tmp_path), "p", tmp_path / "o2.png", client=fc, poll_interval=0,
        reference_images=["https://cdn.example.com/a.jpg"]))
    payload = fc.captured[0][2]
    assert payload["image_urls"] == ["https://cdn.example.com/a.jpg"]


def test_no_reference_images_omits_field(tmp_path):
    """无参考图时不发送 image_urls（纯文生图不受影响）。"""
    import asyncio
    submit = _Resp(200, {"code": 200, "data": [{"task_id": "t3", "status": "submitted"}]})
    done = _Resp(200, {"code": 200, "data": {"id": "t3", "status": "completed",
                                             "result": {"images": [{"url": ["http://x/3.png"]}]}}})
    img = _Resp(200, b"OK3")
    fc = _FakeClient([submit, done, img])
    asyncio.run(imagegen.generate_image(_cfg(tmp_path), "p", tmp_path / "o3.png",
                                        client=fc, poll_interval=0))
    assert "image_urls" not in fc.captured[0][2]
