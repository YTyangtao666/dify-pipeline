"""C3: FastAPI 资产上传 + 一键组图端点。"""
import io
import json

from fastapi.testclient import TestClient

from scripts import api_server


def test_upload_white_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    png = (b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    r1 = client.post("/assets/P001/white", files={"file": ("white.png", io.BytesIO(png), "image/png")})
    assert r1.status_code == 200
    assert "white_1.png" in r1.json()["path"]
    r2 = client.post("/assets/P001/model", files={"file": ("model.jpg", io.BytesIO(png), "image/jpeg")})
    assert r2.status_code == 200


def test_upload_rejects_non_image(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.post("/assets/P001/white", files={"file": ("evil.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code in (400, 415)


def test_assets_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    client.post("/assets/P001/white", files={"file": ("a.png", io.BytesIO(png), "image/png")})
    r = client.get("/assets/P001")
    assert r.status_code == 200
    assert r.json()["white"] == 1


def test_compose_presets_listing():
    client = TestClient(api_server.app)
    r = client.get("/compose/presets")
    assert r.status_code == 200
    body = r.json()
    assert len(body["presets"]) >= 8
    assert all("name" in p and "size" in p for p in body["presets"])


def test_generate_compose_requires_white(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.post("/generate/compose", json={"product_id": "P001", "presets": ["main_white"]})
    assert r.status_code == 400
    assert "白底图" in r.json()["detail"]


def test_file_endpoint_traversal_blocked():
    client = TestClient(api_server.app)
    r = client.get("/file", params={"path": "data/products.json"})
    assert r.status_code == 404
