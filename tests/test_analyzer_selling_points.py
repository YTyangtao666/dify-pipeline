"""L7 卖点提炼与排序测试：映射卖点↔痛点，产出优先级表，Top3 唯一性"""
import json

import pytest

from scripts.pipeline.analyzer import selling_points as sp

PROFILE = {
    "product_id": "P001",
    "audience": {"identity": "上班族女性", "pain": "工位喝水麻烦，杯子不好看"},
    "scenes": ["办公室", "通勤"],
    "selling_points": [
        {"point": "24小时保温", "reason": "随时喝热水"},
        {"point": "316医用内胆", "reason": "食品安全放心"},
        {"point": "云朵挂件设计", "reason": "工位颜值担当"},
        {"point": "一键弹盖", "reason": "单手开盖"},
    ],
}
FEEDBACK = {
    "product_id": "P001",
    "pain_words": [{"word": "保温", "count": 45}, {"word": "拿错杯子", "count": 12}],
    "top_questions": ["能保温多久？", "会不会漏水？"],
    "trust_gaps": ["材质是否安全"],
}
COMPETITORS = {
    "product_id": "P001",
    "price_band": "30-80元",
    "competitors": [
        {"title": "太空杯500ml", "main_points": ["便宜", "大容量"]},
        {"title": "钛杯", "main_points": ["轻", "贵"]},
    ],
    "differentiation": "同价位里颜值+医用材质",
}


class TestBuildPrompt:
    def test_prompt_has_all_inputs(self):
        prompt = sp.build_prompt(PROFILE, FEEDBACK, COMPETITORS)
        for kw in ["24小时保温", "上班族女性", "拿错杯子", "30-80元", "钛杯",
                   "优先级", "Top3", "JSON"]:
            assert kw in prompt

    def test_prompt_missing_feedback_ok(self):
        prompt = sp.build_prompt(PROFILE, None, None)
        assert "24小时保温" in prompt  # 缺输入不崩溃


class TestNormalize:
    def test_top3_exactly_three_when_more(self):
        """红线3：Top3 唯一——LLM 给超过 3 个也只留前 3"""
        raw = {"priority": [
            {"point": "a", "pain": "x", "surface": "主图", "score": 9},
            {"point": "b", "pain": "y", "surface": "主图", "score": 8},
            {"point": "c", "pain": "z", "surface": "详情", "score": 7},
            {"point": "d", "pain": "w", "surface": "详情", "score": 6},
        ]}
        table = sp.normalize_table("P001", raw)
        assert len(table["top3"]) == 3
        assert table["top3"][0]["point"] == "a"
        assert len(table["others"]) == 1

    def test_fewer_than_3_kept_as_is(self):
        raw = {"priority": [{"point": "a", "pain": "x", "surface": "主图", "score": 9}]}
        table = sp.normalize_table("P001", raw)
        assert len(table["top3"]) == 1

    def test_scores_sorted_desc(self):
        raw = {"priority": [
            {"point": "low", "pain": "x", "surface": "主图", "score": 3},
            {"point": "high", "pain": "y", "surface": "主图", "score": 9},
        ]}
        table = sp.normalize_table("P001", raw)
        assert table["top3"][0]["point"] == "high"

    def test_empty_input_degrades(self):
        table = sp.normalize_table("P1", {})
        assert table["top3"] == [] and table["degraded"] is True


class TestAnalyze:
    async def test_analyze_writes_table(self, tmp_path, monkeypatch):
        async def fake_chat(cfg, prompt, **kw):
            assert "24小时保温" in prompt
            return {"priority": [
                {"point": "24小时保温", "pain": "工位喝水麻烦", "surface": "主图", "score": 9},
                {"point": "316医用内胆", "pain": "材质安全顾虑", "surface": "主图", "score": 8},
                {"point": "云朵挂件设计", "pain": "颜值/拿错", "surface": "主图", "score": 7},
                {"point": "一键弹盖", "pain": "操作麻烦", "surface": "详情", "score": 5},
            ]}

        monkeypatch.setattr(sp, "chat_json", fake_chat)
        table = await sp.analyze(PROFILE, FEEDBACK, COMPETITORS, out_dir=tmp_path)
        f = tmp_path / "selling_points_P001.json"
        assert f.exists()
        saved = json.loads(f.read_text(encoding="utf-8"))
        assert [t["point"] for t in saved["top3"]] == ["24小时保温", "316医用内胆", "云朵挂件设计"]
        assert table["degraded"] is False
