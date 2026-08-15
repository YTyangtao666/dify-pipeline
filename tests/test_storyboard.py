"""storyboard 模块测试：8屏视觉逼单结构、行业第7屏映射、提示词构建"""
import json

import pytest

from scripts.pipeline import storyboard


class TestEightScreens:
    def test_screens_have_8_screens_with_full_fields(self):
        screens = storyboard.EIGHT_SCREENS
        assert len(screens) == 8
        for s in screens:
            assert set(s.keys()) >= {"no", "name", "user_question", "task", "evidence"}
        assert screens[0]["name"] == "首屏定位"
        assert screens[7]["name"] == "决策收口"

    def test_screen7_varies_by_category(self):
        """第7屏类目化信任：不同类目不同内容"""
        a = storyboard.screen7_for("吸尘器")
        b = storyboard.screen7_for("服装")
        c = storyboard.screen7_for("猫粮")
        assert a != b != c
        assert "清洗" in a
        assert "尺码" in b
        assert "配料" in c or "储存" in c

    def test_screen7_unknown_category_falls_back(self):
        assert storyboard.screen7_for("未知火星产品") == storyboard.screen7_for("default")


class TestBuildScreenPrompts:
    def test_build_8_prompts_with_product_anchor(self):
        """按产品锚点构建 8 屏提示词：含屏号/主结论/视觉证据/负面约束"""
        product = {
            "product_id": "P001",
            "title": "316不锈钢保温杯 500ml",
            "desc": "316医用级内胆 24小时保温 一键弹盖",
            "category": "保温杯",
        }
        prompts = storyboard.build_screen_prompts(product)
        assert len(prompts) == 8
        # 每条提示词要素
        p1 = prompts[0]
        assert p1["screen_no"] == 1
        assert p1["screen_name"] == "首屏定位"
        assert "保温杯" in p1["prompt"]
        assert "负面" in p1 or "禁止" in p1["prompt"] or "禁止" in p1.get("negative", "")
        # 锚点一致性约束出现在每条里
        for p in prompts:
            assert "316" in p["prompt"] or "保温杯" in p["prompt"]

    def test_prompts_declare_text_reservation(self):
        """首屏要预留标题文案区（手机端可读性）"""
        product = {"product_id": "P1", "title": "保温杯", "desc": "", "category": "保温杯"}
        prompts = storyboard.build_screen_prompts(product)
        assert any("留白" in p["prompt"] or "文案区" in p["prompt"] for p in prompts)

    def test_adjacent_screens_use_different_compositions(self):
        """相邻屏构图不同（原则7：别做成PPT）"""
        product = {"product_id": "P1", "title": "保温杯", "desc": "", "category": "保温杯"}
        prompts = storyboard.build_screen_prompts(product)
        comps = [p.get("composition", "") for p in prompts]
        for i in range(len(comps) - 1):
            assert comps[i] != comps[i + 1]


class TestManifest:
    def test_build_manifest_structure(self, tmp_path):
        product = {"product_id": "P001", "title": "保温杯", "desc": "", "category": "保温杯"}
        m = storyboard.build_manifest(product)
        assert m["product_id"] == "P001"
        assert m["mode"] == "eight-screens"
        assert len(m["screens"]) == 8
        assert m["screens"][0]["file"] == "P001_screen1_首屏定位.png"
