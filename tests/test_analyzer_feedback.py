"""L6 用户反馈测试：京东评论采集（解析）+ LLM 提炼（痛点词云/高频问题/信任缺口）"""
import json

import pytest

from scripts.pipeline.analyzer import feedback as fb

JD_HTML = """
<html><body>
<div class="comment-item" data-comment="正常结构">
  <div class="comment-content"><p>保温效果真的很好，早上装的热水下午还烫嘴。</p></div>
  <div class="comment-info"><span>2026-08-01</span></div>
</div>
<div class="comment-item">
  <div class="comment-content"><p>和同事的杯子拿混了，要是有更多颜色就好了。</p></div>
</div>
<div class="comment-item">
  <div class="comment-content"><p>保温一般般吧，没有说的24小时。</p></div>
</div>
</body></html>
"""


class TestParseComments:
    def test_parses_comments_from_html(self):
        comments = fb.parse_jd_comments(JD_HTML)
        assert len(comments) == 3
        assert "保温效果" in comments[0]
        assert "拿混" in comments[1]

    def test_empty_html(self):
        assert fb.parse_jd_comments("<html></html>") == []

    def test_scrape_keyword(self):
        """采集函数存在且可被 mock（真实网络留给 E2E）"""
        assert callable(fb.scrape_jd_comments)


class TestBuildPrompt:
    def test_prompt_contains_comments(self):
        prompt = fb.build_prompt("P001", ["保温好", "拿混了", "保温一般"])
        for kw in ["P001", "保温好", "拿混", "痛点词云", "信任缺口", "JSON"]:
            assert kw in prompt

    def test_prompt_with_many_comments_truncated(self):
        comments = [f"评论{i}" for i in range(500)]
        prompt = fb.build_prompt("P1", comments)
        assert len(prompt) < 30000  # 防爆 token


class TestNormalize:
    def test_normalize_feedback(self):
        raw = {"pain_words": [{"word": "保温", "count": 45}],
               "top_questions": ["能保温多久？"],
               "trust_gaps": ["材质"]}
        f = fb.normalize_feedback("P001", raw)
        assert f["product_id"] == "P001"
        assert f["pain_words"][0]["count"] == 45
        assert f["degraded"] is False

    def test_flat_pain_words_compat(self):
        """LLM 有时输出纯字符串数组——兼容转 {word, count}"""
        raw = {"pain_words": ["保温", "漏水"], "top_questions": [], "trust_gaps": []}
        f = fb.normalize_feedback("P1", raw)
        assert f["pain_words"][0]["word"] == "保温"
        assert f["pain_words"][0]["count"] == 0

    def test_empty_degrades(self):
        f = fb.normalize_feedback("P1", {})
        assert f["degraded"] is True


class TestAnalyze:
    async def test_analyze_writes_feedback(self, tmp_path, monkeypatch):
        async def fake_chat(cfg, prompt, **kw):
            assert "保温" in prompt
            return {"pain_words": [{"word": "保温", "count": 10}],
                    "top_questions": ["多久？"], "trust_gaps": []}

        monkeypatch.setattr(fb, "chat_json", fake_chat)
        f = await fb.analyze("P001", out_dir=tmp_path, comments=["保温很好"])
        saved = json.loads((tmp_path / "feedback_P001.json").read_text(encoding="utf-8"))
        assert saved["pain_words"][0]["word"] == "保温"
