"""L8 设计方向测试：全量输入 → design_brief（风格/色彩/构图/提示词），与 Top3 一致"""
import json

import pytest

from scripts.pipeline.analyzer import brief as br

PROFILE = {"product_id": "P001", "audience": {"identity": "上班族女性", "pain": "工位喝水麻烦"},
           "scenes": ["办公室", "通勤"],
           "selling_points": [{"point": "24小时保温", "reason": "随时热水"},
                              {"point": "云朵挂件", "reason": "颜值"}]}
TABLE = {"product_id": "P001", "top3": [
    {"point": "24小时保温", "pain": "喝不到热水", "surface": "主图", "score": 9},
    {"point": "云朵挂件", "pain": "丑/拿错", "surface": "主图", "score": 8},
    {"point": "316内胆", "pain": "材质担心", "surface": "主图", "score": 7},
], "others": []}


class TestBuildPrompt:
    def test_prompt_contains_top3_and_context(self):
        prompt = br.build_prompt(PROFILE, TABLE)
        for kw in ["24小时保温", "云朵挂件", "上班族女性", "办公室",
                   "风格", "色彩", "构图", "负面", "JSON"]:
            assert kw in prompt

    def test_prompt_rejects_more_than_top3(self):
        """红线：brief 只围绕 Top3，不被 others 稀释"""
        prompt = br.build_prompt(PROFILE, TABLE)
        assert "Top3" in prompt


class TestNormalize:
    def test_brief_complete_structure(self):
        raw = {
            "style": "日系治愈",
            "color_direction": {"primary": "奶白", "accent": "雾灰"},
            "composition": ["前景大产品", "微距"],
            "keywords": ["治愈", "干净"],
            "negative": ["乱码", "认证标志"],
            "screen_prompts": [{"screen": 1, "prompt": "xxx"}],
        }
        b = br.normalize_brief("P001", raw)
        assert b["product_id"] == "P001"
        assert b["style"] == "日系治愈"
        assert b["color_direction"]["primary"] == "奶白"
        assert len(b["negative"]) >= 1
        assert b["degraded"] is False

    def test_brief_degrades_with_defaults(self):
        b = br.normalize_brief("P1", {})
        assert b["degraded"] is True
        assert b["style"] == ""   # 空但结构完整

    def test_default_negative_always_present(self):
        """统一负面约束必须存在（防编造认证/参数）"""
        raw = {"style": "x", "screen_prompts": []}
        b = br.normalize_brief("P1", raw)
        neg = " ".join(b["negative"])
        assert "认证" in neg or "参数" in neg or "乱码" in neg


class TestAnalyze:
    async def test_analyze_writes_brief(self, tmp_path, monkeypatch):
        async def fake_chat(cfg, prompt, **kw):
            assert "24小时保温" in prompt
            return {"style": "日系治愈", "color_direction": {"primary": "奶白"},
                    "composition": ["前景大产品"], "keywords": ["治愈"],
                    "negative": ["乱码"],
                    "screen_prompts": [{"screen": 1, "prompt": "办公室英雄图"}]}

        monkeypatch.setattr(br, "chat_json", fake_chat)
        b = await br.analyze(PROFILE, TABLE, out_dir=tmp_path)
        f = tmp_path / "design_brief_P001.json"
        assert f.exists()
        saved = json.loads(f.read_text(encoding="utf-8"))
        assert saved["style"] == "日系治愈"
        assert saved["screen_prompts"][0]["screen"] == 1
