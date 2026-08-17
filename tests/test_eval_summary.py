"""T4: 03 质检输出 top3_coverage 摘要——供 Dify 代码节点解析（P2-2 前置）。"""
from scripts.pipeline.evaluator import coverage_pct


def test_coverage_pct_half():
    overall = {"top3_coverage": {"a": 2, "b": 1},
               "items": [{"top3_hits": [{"hit": True}] * 3},
                         {"top3_hits": [{"hit": False}] * 3}]}
    assert abs(coverage_pct(overall) - 50.0) < 0.01


def test_coverage_pct_full_hit():
    overall = {"top3_coverage": {"a": 3},
               "items": [{"top3_hits": [{"hit": True}] * 3}]}
    assert abs(coverage_pct(overall) - 100.0) < 0.01


def test_coverage_pct_none_when_no_top3():
    # styles 模式无 Top3 表 → items 无 top3_hits → None（不卡分支）
    assert coverage_pct({"top3_coverage": {}, "items": [{"top3_hits": []}]}) is None


def test_coverage_pct_real_report_shape():
    # 与 output/eval/eval_report.json 真实结构一致（P002 无 top3 数据混入 P001）
    overall = {"top3_coverage": {"24小时长效保温": 1},
               "items": ([{"top3_hits": [{"hit": True}, {"hit": False}, {"hit": False}]}] * 6
                         + [{"top3_hits": []}] * 6)}
    # P001 6图×3点=18分母, 每图1 hit → 6/18 = 33.33%
    assert abs(coverage_pct(overall) - 33.33) < 0.1
