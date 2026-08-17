"""B3: 套餐 API——列表（含成本预估）、执行、状态查询。"""
import io

from fastapi.testclient import TestClient

from scripts import api_server


def test_bundles_listing_with_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.get("/bundles", params={"product_id": "P001"})
    assert r.status_code == 200
    body = r.json()["bundles"]
    ids = {b["bundle_id"] for b in body}
    assert "tmall_main5" in ids and "full_launch" in ids
    m5 = next(b for b in body if b["bundle_id"] == "tmall_main5")
    # 无素材：runnable=0，成本 0
    assert m5["plan"]["total_runnable"] == 0


def test_bundles_with_white_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    d = tmp_path / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    client = TestClient(api_server.app)
    r = client.get("/bundles", params={"product_id": "P001"})
    m5 = next(b for b in r.json()["bundles"] if b["bundle_id"] == "tmall_main5")
    assert m5["plan"]["total_runnable"] == 5
    assert m5["plan"]["estimated_credits"] > 0


def test_generate_bundle_502_when_no_white(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.post("/generate/bundle", json={"product_id": "P001", "bundle": "tmall_main5"})
    assert r.status_code in (400, 502)


def test_bundle_status_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.get("/bundle/P001/tmall_main5/status")
    assert r.status_code == 200
    assert "state" in r.json()
