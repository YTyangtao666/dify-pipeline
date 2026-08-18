

def test_async_skill_task_lifecycle(tmp_path, monkeypatch):
    """异步任务:提交→返回task_id→轮询到done→manifest可查。"""
    import time as _t
    from fastapi.testclient import TestClient
    from scripts import api_server as srv

    async def fake_gen(cfg, prompt, out_path, **kw):
        _t.sleep(0.05)
        out_path.write_bytes(b"x")
        return None

    monkeypatch.setattr(srv.runner_lib, "generate_image", fake_gen, raising=False)
    import scripts.pipeline.runner as _r
    monkeypatch.setattr(_r, "generate_image", fake_gen)
    monkeypatch.setattr(_r, "_slot_refs", lambda plan, slot: ["data/assets/T001/flat_1.png"])
    monkeypatch.setattr(_r, "_build_slot_prompt", lambda plan, slot, cl: "p")
    # 造素材目录
    from pathlib import Path as _P
    ad = _P.cwd() / "data" / "assets" / "P9"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "flat_1.png").write_bytes(b"x")

    client = TestClient(srv.app)
    r = client.post("/generate/skill/async",
                    json={"skill_id": "shein_official_v1", "product_id": "P9"})
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    assert tid

    deadline = _t.time() + 30
    final = None
    while _t.time() < deadline:
        st = client.get(f"/tasks/{tid}").json()
        if st["state"] in ("done", "failed"):
            final = st
            break
        _t.sleep(0.3)
    assert final and final["state"] == "done", final
    assert final["summary"]["ok"] >= 1
    import shutil as _sh
    _sh.rmtree(_P.cwd() / "output" / "bundles" / "P9_shein_official_v1", ignore_errors=True)
    _sh.rmtree(ad, ignore_errors=True)
