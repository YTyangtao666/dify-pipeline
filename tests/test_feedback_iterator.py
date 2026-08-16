"""L11 归因迭代测试：LLM 四假设归因 → 框架库 score 回流（红线2：唯一入口）"""
import json

import pytest

from scripts.pipeline.feedback import iterator as it

RESULTS = {
    "product_id": "P001",
    "rows": [
        {"image": "P001_screen1_首屏定位.png", "impressions": 12000, "clicks": 360,
         "orders": 18, "carts": 90, "ctr": 0.03, "cvr": 0.05, "cart_rate": 0.0075},
        {"image": "P001_screen5_细节证明.png", "impressions": 12000, "clicks": 120,
         "orders": 2, "carts": 10, "ctr": 0.01, "cvr": 0.0167, "cart_rate": 0.0008},
    ],
    "best": "P001_screen1_首屏定位.png",
    "worst": "P001_screen5_细节证明.png",
}
BRIEF = {"product_id": "P001", "style": "日系治愈",
         "screen_prompts": [{"screen": 1, "name": "首屏定位", "prompt": "奶油白英雄图"},
                            {"screen": 5, "name": "细节证明", "prompt": "微距316"}]}
TABLE = {"product_id": "P001", "top3": [
    {"point": "316医用级内胆", "pain": "材质担心", "surface": "主图", "score": 10},
    {"point": "24小时保温", "pain": "喝不到热水", "surface": "主图", "score": 9},
]}


class TestBuildPrompt:
    def test_prompt_contains_data_and_context(self):
        prompt = it.build_prompt(RESULTS, BRIEF, TABLE)
        for kw in ["3.00%", "5.00%", "首屏定位", "细节证明", "日系治愈", "316医用级内胆",
                   "归因", "JSON"]:
            assert kw in prompt


class TestNormalizeVerdict:
    def test_normalize_valid_verdict(self):
        raw = {"winners": [{"image": "a.png", "why": "痛点直击", "keep": True}],
               "losers": [{"image": "b.png", "why": "卖点错位", "fix": "换构图"}],
               "hypothesis": {"selling_point": True, "audience": False,
                              "style": False, "trust": False},
               "framework_updates": [{"framework_id": "fw_8screen_v1", "win": True,
                                      "evidence": "首屏CTR领先3倍"}]}
        v = it.normalize_verdict("P001", raw)
        assert v["product_id"] == "P001"
        assert v["losers"][0]["fix"] == "换构图"
        assert v["hypothesis"]["selling_point"] is True
        assert len(v["framework_updates"]) == 1

    def test_hypothesis_compat_bool_strings(self):
        """LLM 偶发输出 "true"/"是" 字符串——兼容为布尔"""
        raw = {"hypothesis": {"selling_point": "true", "audience": "否",
                              "style": True, "trust": False}}
        v = it.normalize_verdict("P1", raw)
        assert v["hypothesis"] == {"selling_point": True, "audience": False,
                                   "style": True, "trust": False}

    def test_empty_degrades(self):
        v = it.normalize_verdict("P1", {})
        assert v["degraded"] is True
        assert v["framework_updates"] == []


class TestApplyToFramework:
    def test_apply_updates_score_via_only_entry(self, tmp_path):
        """红线2：score 只经 framework.update_score 修改"""
        from scripts.pipeline.analyzer import framework as fw
        lib = fw.FrameworkLibrary(tmp_path / "frameworks.json")
        before = lib.get("fw_8screen_v1")["score"]["wins"]
        verdict = {"framework_updates": [
            {"framework_id": "fw_8screen_v1", "win": True, "evidence": "x"}]}
        applied = it.apply_to_frameworks(verdict, lib)
        assert applied == 1
        assert lib.get("fw_8screen_v1")["score"]["wins"] == before + 1

    def test_apply_skips_unknown_framework(self, tmp_path):
        from scripts.pipeline.analyzer import framework as fw
        lib = fw.FrameworkLibrary(tmp_path / "frameworks.json")
        verdict = {"framework_updates": [
            {"framework_id": "fw_nope", "win": True, "evidence": "x"}]}
        applied = it.apply_to_frameworks(verdict, lib)
        assert applied == 0  # 未知框架跳过不崩


class TestIterate:
    async def test_iterate_full_flow(self, tmp_path, monkeypatch):
        async def fake_chat(cfg, prompt, **kw):
            return {"winners": [{"image": "P001_screen1_首屏定位.png", "why": "好", "keep": True}],
                    "losers": [], "hypothesis": {"selling_point": True, "audience": False,
                                                 "style": False, "trust": False},
                    "framework_updates": [{"framework_id": "fw_8screen_v1", "win": True,
                                           "evidence": "首屏胜"}]}

        monkeypatch.setattr(it, "chat_json", fake_chat)
        from scripts.pipeline.analyzer import framework as fw
        lib = fw.FrameworkLibrary(tmp_path / "frameworks.json")

        v = await it.iterate(RESULTS, BRIEF, TABLE, lib=lib, out_dir=tmp_path)
        assert (tmp_path / "iteration_P001.json").exists()
        assert lib.get("fw_8screen_v1")["score"]["wins"] == 1
        assert v["degraded"] is False
