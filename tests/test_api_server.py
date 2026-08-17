"""T3: API 失败码透传——脚本非零退出必须映射 HTTP 502，消灭「生图0张仍succeeded」。"""
from fastapi.testclient import TestClient

from scripts import api_server


class _R:
    """模拟 subprocess.run 结果"""

    def __init__(self, rc: int, out: str = "out", err: str = ""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def test_generate_nonzero_exit_maps_502(monkeypatch):
    monkeypatch.setattr(api_server.subprocess, "run", lambda *a, **k: _R(3))
    r = TestClient(api_server.app).post("/generate?limit=1")
    assert r.status_code == 502
    assert r.json()["code"] == 3


def test_generate_zero_exit_maps_200(monkeypatch):
    monkeypatch.setattr(api_server.subprocess, "run", lambda *a, **k: _R(0))
    r = TestClient(api_server.app).post("/generate?limit=1")
    assert r.status_code == 200


def test_video_nonzero_exit_maps_502(monkeypatch):
    monkeypatch.setattr(api_server.subprocess, "run", lambda *a, **k: _R(3))
    r = TestClient(api_server.app).post("/video/P001")
    assert r.status_code == 502


def test_health_always_200_no_subprocess():
    r = TestClient(api_server.app).get("/health")
    assert r.status_code == 200
