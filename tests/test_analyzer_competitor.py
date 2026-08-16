"""L2 竞品分析测试：京东同类目爬取复用 + LLM 对比定位（价格带/卖点/差异化）"""
import json

import pytest

from scripts.pipeline.analyzer import competitor as comp

PRODUCT = {"product_id": "P001", "title": "316不锈钢保温杯 500ml",
           "desc": "316医用内胆 24小时保温", "price": 59.9, "category": "保温杯"}
COMP_ITEMS = [
    {"product_id": "C1", "title": "钛合金保温杯 450ml 轻量", "price": 189.0, "shop": "A店"},
    {"product_id": "C2", "title": "大容量保温杯 800ml 运动款", "price": 39.9, "shop": "B店"},
    {"product_id": "C3", "title": "316不锈钢保温杯 500ml 简约", "price": 55.0, "shop": "C店"},
]


class TestBuildPrompt:
    def test_prompt_has_product_and_competitors(self):
        prompt = comp.build_prompt(PRODUCT, COMP_ITEMS)
        for kw in ["316不锈钢保温杯", "59.9", "钛合金", "189.0", "39.9",
                   "价格带", "差异化", "JSON"]:
            assert kw in prompt

    def test_no_competitors_degrades(self):
        prompt = comp.build_prompt(PRODUCT, [])
        assert "316不锈钢保温杯" in prompt


class TestNormalize:
    def test_normalize_competitor_report(self):
        raw = {"price_band": "30-80元", "our_position": "中端",
               "competitors": [{"title": "钛杯", "price": 189, "main_points": ["轻", "贵"]}],
               "differentiation": "同价位医用材质+颜值"}
        r = comp.normalize_report("P001", raw)
        assert r["price_band"] == "30-80元"
        assert r["competitors"][0]["main_points"] == ["轻", "贵"]
        assert r["degraded"] is False

    def test_flat_fields_compat(self):
        raw = {"competitors": [{"title": "x", "main_points": "便宜"}]}  # 字符串型卖点
        r = comp.normalize_report("P1", raw)
        assert r["competitors"][0]["main_points"] == ["便宜"]

    def test_empty_degrades(self):
        r = comp.normalize_report("P1", {})
        assert r["degraded"] is True


class TestCollectCompetitors:
    def test_collect_excludes_self_and_dedups(self, monkeypatch):
        """爬取结果去重 + 剔除与自身完全同标题的项"""
        async def fake_scrape(keyword, limit=5, headless=True):
            return [
                {"product_id": "C1", "title": "钛合金保温杯", "price": 189.0, "shop": "A"},
                {"product_id": "C1", "title": "钛合金保温杯", "price": 189.0, "shop": "A"},  # 重复
                {"product_id": "C2", "title": "316不锈钢保温杯 500ml 简约", "price": 55.0, "shop": "C"},
                {"product_id": "P001", "title": "316不锈钢保温杯 500ml", "price": 59.9, "shop": "自营"},  # 自身近似
            ]

        from scripts.pipeline import scraper as scr
        monkeypatch.setattr(scr, "scrape_jd", fake_scrape)
        items = comp.collect_competitors(PRODUCT, limit=5)
        ids = [i["product_id"] for i in items]
        assert ids.count("C1") == 1

    def test_collect_scrape_failure_returns_empty(self, monkeypatch):
        from scripts.pipeline import scraper as scr
        async def boom(keyword, limit=5, headless=True):
            raise RuntimeError("反爬")
        monkeypatch.setattr(scr, "scrape_jd", boom)
        items = comp.collect_competitors(PRODUCT)
        assert items == []


class TestAnalyze:
    async def test_analyze_writes_report(self, tmp_path, monkeypatch):
        async def fake_chat(cfg, prompt, **kw):
            assert "钛合金" in prompt
            return {"price_band": "30-80", "our_position": "中端",
                    "competitors": [], "differentiation": "医用材质"}

        monkeypatch.setattr(comp, "chat_json", fake_chat)
        monkeypatch.setattr(comp, "collect_competitors", lambda p, limit=5: COMP_ITEMS[:2])
        r = await comp.analyze(PRODUCT, out_dir=tmp_path)
        saved = json.loads((tmp_path / "competitors_P001.json").read_text(encoding="utf-8"))
        assert saved["price_band"] == "30-80"
