"""L1 产品分析测试：商品主档 → 人群画像/使用场景/核心卖点清单"""
import json

import pytest

from scripts.pipeline.analyzer import product as prod


class TestBuildPrompt:
    def test_prompt_contains_product_facts(self):
        p = {"product_id": "P001", "title": "316不锈钢保温杯 500ml",
             "desc": "316医用级内胆 24小时保温", "price": 59.9, "category": "保温杯"}
        prompt = prod.build_prompt(p)
        for kw in ["316不锈钢保温杯", "316医用级内胆", "59.9", "保温杯",
                   "人群画像", "使用场景", "核心卖点"]:
            assert kw in prompt, f"prompt 缺少 {kw}"
        # 要求结构化输出
        assert "JSON" in prompt

    def test_prompt_handles_missing_fields(self):
        p = {"product_id": "P2", "title": "未知商品", "desc": ""}
        prompt = prod.build_prompt(p)
        assert "未知商品" in prompt  # 不崩溃


class TestNormalizeProfile:
    def test_normalize_valid_profile(self):
        raw = {
            "audience": {"age": "22-35", "identity": "上班族女性", "pain": "喝水麻烦"},
            "scenes": ["办公室", "通勤"],
            "selling_points": [{"point": "24小时保温", "reason": "随时喝热水"},
                               {"point": "316内胆", "reason": "食品安全"}],
        }
        profile = prod.normalize_profile("P001", raw)
        assert profile["product_id"] == "P001"
        assert profile["audience"]["identity"] == "上班族女性"
        assert len(profile["scenes"]) == 2
        assert len(profile["selling_points"]) == 2

    def test_normalize_fills_defaults_for_missing(self):
        """LLM 漏字段 → 结构化兜底而非崩溃（红线4：单层降级）"""
        profile = prod.normalize_profile("P1", {})
        assert profile["product_id"] == "P1"
        assert profile["audience"]["identity"] == ""
        assert profile["scenes"] == []
        assert profile["selling_points"] == []
        assert profile["degraded"] is True

    def test_normalize_accepts_flat_selling_points(self):
        """LLM 有时输出纯字符串列表——兼容"""
        raw = {"audience": {"identity": "x"}, "scenes": ["y"], "selling_points": ["保温", "便携"]}
        profile = prod.normalize_profile("P1", raw)
        assert profile["selling_points"][0]["point"] == "保温"


class TestAnalyze:
    async def test_analyze_writes_profile_json(self, tmp_path, monkeypatch):
        """端到端：mock LLM → 落盘 product_profile_{pid}.json"""
        async def fake_chat(cfg, prompt, **kw):
            return {"audience": {"identity": "学生党"}, "scenes": ["教室"],
                    "selling_points": [{"point": "大容量", "reason": "一天够喝"}]}

        monkeypatch.setattr(prod, "chat_json", fake_chat)
        p = {"product_id": "P001", "title": "保温杯", "desc": "", "price": 59.9}
        out = await prod.analyze(p, out_dir=tmp_path)
        f = tmp_path / "product_profile_P001.json"
        assert f.exists()
        saved = json.loads(f.read_text(encoding="utf-8"))
        assert saved["audience"]["identity"] == "学生党"
        assert out == saved
