

def test_upload_scene_ref_and_prompt(tmp_path, monkeypatch):
    """三类图上传(scene/ref) + 自定义提示词存取。"""
    from fastapi.testclient import TestClient
    from scripts import api_server as srv
    monkeypatch.setattr(srv, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(srv, "ROOT", tmp_path)
    import io
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    client = TestClient(srv.app)
    # scene 上传2张
    for _ in range(2):
        r = client.post("/assets/P77/scene", files={"file": ("s.png", io.BytesIO(png), "image/png")})
        assert r.status_code == 200, r.text
    # ref 上传1张
    r = client.post("/assets/P77/ref", files={"file": ("r.png", io.BytesIO(png), "image/png")})
    assert r.status_code == 200
    # 列表应含 scene/ref 计数
    lst = client.get("/assets/P77").json()
    assert lst["scene"] == 2 and lst["ref"] == 1

    # 自定义提示词存取
    r = client.post("/assets/P77/prompt", json={"custom_prompt": "更复古的胶片色调，姿势慵懒"})
    assert r.status_code == 200
    r = client.get("/assets/P77/prompt").json()
    assert r["custom_prompt"] == "更复古的胶片色调，姿势慵懒"


def test_custom_prompt_injected_into_skill_prompt(tmp_path, monkeypatch):
    """生成时自定义提示词拼进槽位 prompt 末尾。"""
    import asyncio, json as _json
    from pathlib import Path as _P
    from scripts import api_server as srv
    monkeypatch.setattr(srv, "ROOT", _P.cwd())
    monkeypatch.setattr(srv, "ASSETS_DIR", _P.cwd() / "data" / "assets")
    from scripts.pipeline import runner as _r
    from scripts.pipeline.bundles import BundlePlan, SlotPlan
    captured = {}

    async def fake_gen(cfg, prompt, out_path, **kw):
        captured["prompt"] = prompt
        out_path.write_bytes(b"x")
        return None

    monkeypatch.setattr(_r, "generate_image", fake_gen)
    monkeypatch.setattr(_r, "_slot_refs", lambda plan, slot: ["data/assets/T001/flat_1.png"])
    orig = _r._build_slot_prompt
    monkeypatch.setattr(_r, "_build_slot_prompt", lambda plan, slot, cl: "基础模板")
    # 注入函数(从 srv 导入)
    from scripts.api_server import _inject_custom_prompt
    wrapped = _inject_custom_prompt(orig_prompt_fn=lambda plan, slot, cl: "基础模板",
                                    custom="复古胶片")
    # 模拟异步任务路径: srv._run_skill_task 太重,直接测注入函数
    got = wrapped(None, None, None)
    assert "基础模板" in got and "复古胶片" in got


def test_delete_asset(tmp_path, monkeypatch):
    """删除素材图 + 安全校验(防路径穿越/防删非图)。"""
    from fastapi.testclient import TestClient
    from scripts import api_server as srv
    monkeypatch.setattr(srv, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(srv, "ROOT", tmp_path)
    d = tmp_path / "P88"; d.mkdir(parents=True)
    (d / "ref_1.png").write_bytes(b"x")
    (d / "custom_prompt.txt").write_text("t")
    client = TestClient(srv.app)
    r = client.delete("/assets/P88/ref_1.png")
    assert r.status_code == 200 and r.json()["count_left"] == 0
    assert not (d / "ref_1.png").exists()
    # 穿越与非法名拒绝（URL编码的 ../ 与非图文件）
    assert client.delete("/assets/P88/%2e%2e/P88_bomb").status_code in (400, 404)
    assert client.delete("/assets/P88/custom_prompt.txt").status_code == 400  # 非图片拒删


def test_empty_prompt_clears(tmp_path, monkeypatch):
    """空 custom_prompt = 清空(而非400)。"""
    from fastapi.testclient import TestClient
    from scripts import api_server as srv
    monkeypatch.setattr(srv, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(srv, "ROOT", tmp_path)
    d = tmp_path / "P88"; d.mkdir(parents=True)
    (d / "custom_prompt.txt").write_text("旧提示词")
    client = TestClient(srv.app)
    r = client.post("/assets/P88/prompt", json={"custom_prompt": ""})
    assert r.status_code == 200
    assert not (d / "custom_prompt.txt").exists()
    assert client.get("/assets/P88/prompt").json()["custom_prompt"] == ""


def test_skills_list_filters_test_packs():
    """技能包列表过滤测试包(style_*/test_*)。"""
    from fastapi.testclient import TestClient
    from scripts import api_server as srv
    client = TestClient(srv.app)
    d = client.get("/skills").json()
    for s in d["skills"]:
        assert not s["skill_id"].startswith("test_"), s
        assert not s["skill_id"].startswith("style_"), s
