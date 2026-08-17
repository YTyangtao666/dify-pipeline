"""B1: 套餐（Bundle）定义——带位置语义的素材清单。"""
import pytest

from scripts.pipeline.bundles import BUNDLES, get_bundle, plan_bundle, BundlePlan, SlotPlan


def test_bundles_registry_has_core_packs():
    assert "tmall_main5" in BUNDLES
    assert "xhs_pack6" in BUNDLES
    assert "detail_8screen" in BUNDLES
    assert "ab_test6" in BUNDLES
    assert "full_launch" in BUNDLES


def test_tmall_main5_slot_structure():
    b = get_bundle("tmall_main5")
    assert len(b["slots"]) == 5
    roles = [s["role"] for s in b["slots"]]
    assert roles[0] == "白底规范图"
    # 每槽位必备字段
    for s in b["slots"]:
        assert s["pos"] >= 1 and s["preset"] and s["size"]


def test_plan_skips_slots_missing_model(tmp_path):
    """缺模特图的槽位自动跳过并标注原因，不阻塞整包。"""
    # 素材：只有白底图
    d = tmp_path / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    plan = plan_bundle("P001", "tmall_main5", assets_dir=tmp_path)
    assert isinstance(plan, BundlePlan)
    skipped = [s for s in plan.slots if not s.runnable]
    assert all("模特" in s.skip_reason for s in skipped)
    # tmall_main5 不需要模特图 → 全部可跑
    assert len(skipped) == 0
    assert plan.total_runnable == 5


def test_plan_blocks_when_no_white(tmp_path):
    d = tmp_path / "P001"
    d.mkdir()
    plan = plan_bundle("P001", "tmall_main5", assets_dir=tmp_path)
    assert plan.total_runnable == 0
    assert all("白底图" in s.skip_reason for s in plan.slots)


def test_plan_names_files_by_position(tmp_path):
    d = tmp_path / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    plan = plan_bundle("P001", "tmall_main5", assets_dir=tmp_path)
    names = [s.filename for s in plan.slots]
    assert "P001_main1_白底规范图.png" in names
    assert "P001_main2_核心卖点图.png" in names


def test_full_launch_composition():
    """full_launch = 组合包：包含子包全部槽位。"""
    plan = plan_bundle("P001", "full_launch", assets_dir=_assets())
    total = len(BUNDLES["tmall_main5"]["slots"]) + len(BUNDLES["xhs_pack6"]["slots"])
    assert len(plan.slots) == total


def test_cost_estimate_in_plan(tmp_path):
    d = tmp_path / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    plan = plan_bundle("P001", "tmall_main5", assets_dir=tmp_path)
    assert plan.estimated_credits > 0
    assert plan.estimated_seconds > 0


def test_ab_test_variants(tmp_path):
    """ab_test6：同一构图 × 6 文案钩子变体——赛马组。"""
    d = tmp_path / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    plan = plan_bundle("P001", "ab_test6", assets_dir=tmp_path, variants=2)
    # 每个基础槽位 × variants
    assert plan.total_runnable == len(BUNDLES["ab_test6"]["slots"]) * 2
    variant_names = [s.filename for s in plan.slots if "v2" in s.filename]
    assert variant_names  # 有 v2 变体命名


def _assets():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    d = tmp / "P001"
    d.mkdir()
    (d / "white_1.png").write_bytes(b"x")
    (d / "model_1.png").write_bytes(b"x")
    return tmp
