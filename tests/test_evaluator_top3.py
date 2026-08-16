"""03 质检升级测试：评分标准从美观升级为「是否打穿 Top3 卖点」"""
import json

import pytest

from scripts.pipeline import evaluator


class TestTop3Prompt:
    def test_prompt_injects_top3_when_table_exists(self, tmp_path, monkeypatch):
        """有卖点表 → EVAL_PROMPT 注入 Top3 质检维度"""
        table = {"top3": [
            {"point": "316医用级内胆", "pain": "材质担心", "surface": "主图", "score": 10},
            {"point": "24小时保温", "pain": "没热水喝", "surface": "主图", "score": 9},
        ]}
        prompt = evaluator.build_eval_prompt("保温杯", top3_table=table)
        assert "316医用级内胆" in prompt
        assert "打穿" in prompt or "传达" in prompt

    def test_prompt_without_table_falls_back(self):
        prompt = evaluator.build_eval_prompt("保温杯", top3_table=None)
        assert "保温杯" in prompt
        assert "打穿" not in prompt or "卖点" in prompt  # 兼容旧语义


class TestVerdictTop3:
    def test_verdict_carries_top3_hits(self):
        """解析 LLM 输出的 top3_hits（每条卖点是否被图传达）"""
        content = json.dumps({
            "usable": True, "score": 88,
            "issues": [],
            "top3_hits": [{"point": "316医用级内胆", "hit": True},
                          {"point": "24小时保温", "hit": False}],
        }, ensure_ascii=False)
        data = evaluator.extract_json(content)
        v = evaluator.Verdict(
            usable=bool(data.get("usable")),
            score=int(data.get("score") or 0),
            issues=list(data.get("issues") or []),
            top3_hits=list(data.get("top3_hits") or []),
        )
        assert v.top3_hits[0]["hit"] is True
        assert v.top3_hits[1]["hit"] is False


class TestReportTop3:
    def test_report_aggregates_top3_coverage(self):
        """报告新增 top3_coverage：每条卖点被多少张图打穿"""
        verdicts = [
            evaluator.Verdict(usable=True, score=90, top3_hits=[
                {"point": "316内胆", "hit": True}, {"point": "24h保温", "hit": True}]),
            evaluator.Verdict(usable=True, score=88, top3_hits=[
                {"point": "316内胆", "hit": True}, {"point": "24h保温", "hit": False}]),
            evaluator.Verdict(usable=True, score=85, top3_hits=[
                {"point": "316内胆", "hit": False}, {"point": "24h保温", "hit": False}]),
        ]
        report = evaluator.build_report(verdicts)
        cov = report["top3_coverage"]
        assert cov["316内胆"] == 2
        assert cov["24h保温"] == 1
