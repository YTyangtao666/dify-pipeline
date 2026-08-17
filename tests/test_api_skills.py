"""S3: 技能包 API——学习/列表/一键应用。"""
import io

from fastapi.testclient import TestClient

from scripts import api_server


def test_learn_skill_from_images(tmp_path, monkeypatch):
    """上传样例图 → VLM 逆向分析（mock）→ 技能包落盘。"""
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    # mock style_learner 的 VLM 分析函数
    import scripts.pipeline.style_learner as sl
    fake = {"type": "模特正面生活图", "composition": "半身，虚化背景",
            "lighting": "柔光", "pose": "自然", "framing": "中景"}

    async def fake_vlm(p):
        return fake
    monkeypatch.setattr(sl, "analyze_image_vlm", fake_vlm)
    monkeypatch.setattr(api_server.style_learner_lib, "analyze_image_vlm", fake_vlm)

    client = TestClient(api_server.app)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 30
    files = [("files", ("s1.png", io.BytesIO(png), "image/png")),
             ("files", ("s2.png", io.BytesIO(png), "image/png"))]
    r = client.post("/skills/learn",
                    data={"skill_id": "test_casual", "name": "休闲风"},
                    files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill_id"] == "test_casual"
    assert len(body["slots"]) >= 1
    assert body["slots"][0]["input_deps"] == ["flat", "model"]


def test_skills_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.get("/skills")
    assert r.status_code == 200
    assert "skills" in r.json()


def test_generate_skill_requires_assets(tmp_path, monkeypatch):
    """无素材 → 400 明确提示。"""
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    r = client.post("/generate/skill", json={"skill_id": "nope", "product_id": "P001"})
    assert r.status_code in (400, 404)


def test_generate_skill_missing_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "ASSETS_DIR", tmp_path)
    client = TestClient(api_server.app)
    # 先造一个合法技能包但商品无素材 → 400（缺素材提示）
    import json as _json
    from scripts.pipeline import style_learner as sl
    pack = {"skill_id": "s_x", "name": "x", "created": "t",
            "slots": [{"pos": 1, "role": "白底平铺图", "size": "1:1",
                       "input_deps": ["flat"], "template": "生成白底图 {title}"}],
            "quality_bar": {}}
    d = tmp_path / "skills"
    d.mkdir(parents=True)
    (d / "s_x.json").write_text(_json.dumps(pack, ensure_ascii=False))
    r = client.post("/generate/skill", json={"skill_id": "s_x", "product_id": "P001"})
    assert r.status_code == 400
    assert "平铺图" in r.json()["detail"] or "素材" in r.json()["detail"]
