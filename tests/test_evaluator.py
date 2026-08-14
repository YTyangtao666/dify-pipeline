"""evaluator 模块测试：VLM 评分调用 + usable_rate/top_issue 解析 + 报告聚合"""
import json

import httpx
import pytest
import respx

from scripts.pipeline.config import Config

BASE = "https://yunwu.test/v1"


def make_config(tmp_path):
    return Config(base_url=BASE, api_key="sk-t", image_model="m",
                  vlm_model="vlm", llm_model="llm", out_dir=tmp_path)


def vlm_ok_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class TestEvaluateImage:
    async def test_parses_vlm_json_verdict(self, tmp_path):
        """VLM 返回 JSON 判定 → 解析出 pass/score/issues"""
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        verdict_json = json.dumps({
            "usable": True, "score": 88,
            "issues": [{"type": "构图", "note": "主体略偏左"}],
        }, ensure_ascii=False)
        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(
                return_value=vlm_ok_response(f"```json\n{verdict_json}\n```"))
            v = await evaluator.evaluate_image(cfg, img, product_title="保温杯")

        assert v.usable is True
        assert v.score == 88
        assert v.issues[0]["type"] == "构图"

    async def test_vlm_unparsable_marks_unusable(self, tmp_path):
        """VLM 输出无法解析 → 判不可用而非崩溃"""
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(
                return_value=vlm_ok_response("这张图很好看！"))
            v = await evaluator.evaluate_image(cfg, img, product_title="保温杯")

        assert v.usable is False
        assert v.score == 0
        assert v.parse_ok is False

    async def test_retries_on_5xx(self, tmp_path):
        from scripts.pipeline import evaluator

        cfg = make_config(tmp_path)
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        calls = {"n": 0}

        def flaky(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, json={"e": 1})
            return vlm_ok_response('{"usable": true, "score": 90, "issues": []}')

        with respx.mock(base_url=BASE) as mock:
            mock.post("/chat/completions").mock(side_effect=flaky)
            v = await evaluator.evaluate_image(cfg, img, product_title="x")

        assert calls["n"] == 2 and v.usable is True


class TestReport:
    def test_report_usable_rate_and_top_issue(self, tmp_path):
        """聚合报告：可用率 + 最高频问题"""
        from scripts.pipeline import evaluator

        verdicts = [
            evaluator.Verdict(usable=True, score=90, issues=[]),
            evaluator.Verdict(usable=False, score=40, issues=[{"type": "文字乱码"}, {"type": "构图"}]),
            evaluator.Verdict(usable=False, score=50, issues=[{"type": "文字乱码"}]),
            evaluator.Verdict(usable=True, score=85, issues=[]),
            evaluator.Verdict(usable=False, score=30, issues=[{"type": "主体变形"}]),
        ]
        report = evaluator.build_report(verdicts)
        assert report["usable_rate"] == pytest.approx(40.0)
        assert report["top_issue"] == "文字乱码"
        assert report["total"] == 5

    def test_report_all_pass_no_issue(self):
        from scripts.pipeline import evaluator

        verdicts = [evaluator.Verdict(usable=True, score=95, issues=[]) for _ in range(3)]
        report = evaluator.build_report(verdicts)
        assert report["usable_rate"] == 100.0
        assert report["top_issue"] == ""
