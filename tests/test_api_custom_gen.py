

def test_generate_custom_endpoint(tmp_path, monkeypatch):
    """自定义prompt单图生成: 参考图自动取素材, count控制张数。"""
    from fastapi.testclient import TestClient
    from scripts import api_server as srv
    monkeypatch.setattr(srv, "ROOT", tmp_path)
    monkeypatch.setattr(srv, "ASSETS_DIR", tmp_path / "data" / "assets")
    calls = []

    class FakeGen:
        def __init__(self, cfg=None):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    import asyncio

    async def fake_generate(cfg, prompt, out_path, **kw):
        calls.append({"prompt": prompt, "refs": kw.get("reference_images")})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"img")
        return None

    import scripts.pipeline.imagegen as ig
    monkeypatch.setattr(ig, "build_client", lambda cfg: FakeGen())
    monkeypatch.setattr(ig, "generate_image", fake_generate)

    d = tmp_path / "data" / "assets" / "PX"
    d.mkdir(parents=True)
    (d / "ref_1.png").write_bytes(b"r")
    (d / "flat_1.png").write_bytes(b"f")

    client = TestClient(srv.app)
    r = client.post("/generate/custom", json={
        "prompt": "六色系列封面图", "product_id": "PX", "count": 2, "size": "4:5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2 and len(body["images"]) == 2
    assert any("ref_1" in str(c["refs"][0]) for c in calls)
    assert "六色系列封面图" in calls[0]["prompt"]
