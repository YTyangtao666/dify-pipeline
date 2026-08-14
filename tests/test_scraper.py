"""scraper 模块测试：京东HTML解析 + JSON兜底 + 归一化"""
import json

import pytest

from scripts.pipeline import scraper

# 京东搜索结果页 gl-item 卡片的最小结构（2026-08 版）
JD_HTML = """
<html><body>
<div class="gl-item" data-sku="100012043978">
  <div class="p-img"><a href="//item.jd.com/100012043978.html"><img data-lazy-img="//img14.360buyimg.com/apple.jpg"/></a></div>
  <div class="p-name"><a><em>Apple iPhone 15 Pro 256GB 原色钛金属</em></a></div>
  <div class="p-price"><strong><i data-price="7999">¥7999</i></strong></div>
  <div class="p-shop"><a>Apple自营旗舰店</a></div>
</div>
<div class="gl-item" data-sku="100054601187">
  <div class="p-img"><a href="//item.jd.com/100054601187.html"><img data-lazy-img="//img14.360buyimg.com/xiaomi.jpg"/></a></div>
  <div class="p-name"><a><em>小米14 Ultra 16+512 黑色 5G手机</em></a></div>
  <div class="p-price"><strong><i data-price="5999">¥5999</i></strong></div>
  <div class="p-shop"><a>小米自营旗舰店</a></div>
</div>
</body></html>
"""


class TestParseJD:
    def test_parses_items_from_html(self):
        products = scraper.parse_jd_html(JD_HTML, keyword="手机")
        assert len(products) == 2
        p = products[0]
        assert p["product_id"] == "100012043978"
        assert "iPhone 15 Pro" in p["title"]
        assert p["price"] == 7999.0
        assert p["shop"] == "Apple自营旗舰店"
        assert p["image"].startswith("https://")
        assert p["url"].startswith("https://item.jd.com/100012043978")
        assert p["keyword"] == "手机"

    def test_empty_html_returns_empty(self):
        assert scraper.parse_jd_html("<html><body></body></html>", "k") == []


class TestNormalize:
    def test_load_products_json(self, tmp_path):
        """兜底：直接读 products.json（用户手工提供）"""
        f = tmp_path / "products.json"
        f.write_text(json.dumps([
            {"product_id": "P001", "title": "保温杯", "price": 59.9, "desc": "316不锈钢"},
        ], ensure_ascii=False), encoding="utf-8")
        products = scraper.load_products(f)
        assert products[0]["product_id"] == "P001"
        assert products[0].setdefault("shop", "") == ""

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            scraper.load_products(tmp_path / "nope.json")


class TestPromptBuild:
    def test_build_gen_prompt_includes_title_and_style(self):
        p = {"product_id": "P1", "title": "便携榨汁杯", "desc": "USB充电 出差必备"}
        s = scraper.build_gen_prompt(p, style="ins风")
        assert "便携榨汁杯" in s and "ins风" in s and "USB充电" in s

    def test_build_video_script(self):
        p = {"product_id": "P1", "title": "便携榨汁杯", "desc": "15秒出汁"}
        script = scraper.build_video_script(p)
        assert "便携榨汁杯" in script["tts_text"]
        assert script["tts_text"]  # 非空
        assert isinstance(script["duration_est"], float)
