"""S1-S2: 风格学习器——样例图集 → 技能包。"""
import json
from pathlib import Path

import pytest

from scripts.pipeline import style_learner as sl


def test_analyze_image_builds_prompt_hint(tmp_path):
    """单图分析：VLM 返回结构化要素 → 产出 prompt_hint。"""
    fake_vlm = {
        "type": "模特正面生活图",
        "composition": "半身出镜，自然姿势，背景大光圈虚化咖啡馆",
        "lighting": "顶部柔和主光+前方补光",
        "pose": "单手轻抚头发，微侧身",
        "framing": "胸到腰中景",
        "input_deps": ["flat", "model"],
    }
    hint = sl.build_prompt_hint(fake_vlm)
    assert "半身" in hint and "虚化" in hint
    assert "顶部柔和主光" in hint


def test_infer_deps_from_analysis():
    """从 VLM 描述推断输入依赖：有模特→model+服装载体。"""
    assert sl.infer_deps({"type": "模特正面生活图"}) == ["flat", "model"]
    assert sl.infer_deps({"type": "白底平铺图"}) == ["flat"]
    assert sl.infer_deps({"type": "场景种草图"}) == ["flat", "model"]


def test_cluster_slots_merges_same_type():
    """同类型样例合并为一个槽位（取共性），不同类型分开。"""
    analyses = [
        {"type": "模特正面生活图", "composition": "半身，背景虚化", "lighting": "柔光",
         "pose": "自然", "framing": "中景", "input_deps": ["flat", "model"]},
        {"type": "模特正面生活图", "composition": "半身，背景虚化街道", "lighting": "自然光",
         "pose": "行走", "framing": "中景", "input_deps": ["flat", "model"]},
        {"type": "白底平铺图", "composition": "居中", "lighting": "均匀漫射",
         "pose": "", "framing": "全身", "input_deps": ["flat"]},
    ]
    slots = sl.cluster_slots(analyses)
    assert len(slots) == 2  # 合并后 2 种
    roles = [s["role"] for s in slots]
    assert "模特正面生活图" in roles and "白底平铺图" in roles
    # 合并槽位的 template 融合两份构图描述
    merged = next(s for s in slots if s["role"] == "模特正面生活图")
    assert "背景虚化" in merged["template"]


def test_make_skill_pack_schema(tmp_path):
    """技能包落盘 schema 完整可回读。"""
    slots = sl.cluster_slots([
        {"type": "白底平铺图", "composition": "居中", "lighting": "漫射",
         "pose": "", "framing": "全身", "input_deps": ["flat"]},
    ])
    pack = sl.make_skill_pack("test_style", "测试风格", slots,
                              sample_dir=tmp_path, title_hint="服装")
    assert pack["skill_id"] == "test_style"
    assert pack["slots"][0]["pos"] == 1
    p = sl.save_skill_pack(pack, data_dir=tmp_path)
    loaded = json.loads(Path(p).read_text(encoding="utf-8"))
    assert loaded["skill_id"] == "test_style"
    sl.validate_skill_pack(loaded)  # 不抛异常即合法


def test_validate_rejects_broken_pack():
    with pytest.raises(ValueError):
        sl.validate_skill_pack({"skill_id": "x", "slots": []})  # 无槽位
    with pytest.raises(ValueError):
        sl.validate_skill_pack({"skill_id": "x", "slots": [
            {"pos": 1, "role": "r", "input_deps": ["flat"]}]})  # 缺 template


def test_template_placeholders():
    """template 必须含 {title}，可选卖点/价格占位符。"""
    slots = sl.cluster_slots([
        {"type": "白底平铺图", "composition": "居中展示", "lighting": "漫射",
         "pose": "", "framing": "全身", "input_deps": ["flat"]},
    ])
    assert "{title}" in slots[0]["template"]


def test_fashion_redlines_attached_for_model_slots():
    """含 model 的槽位 template 自动附加三红线。"""
    slots = sl.cluster_slots([
        {"type": "模特正面生活图", "composition": "半身", "lighting": "柔光",
         "pose": "自然", "framing": "中景", "input_deps": ["flat", "model"]},
    ])
    t = slots[0]["template"]
    assert "100% 一致" in t      # MODEL_ANCHOR
    assert "大长腿" in t          # BODY_DIRECTIVE
    assert "毛孔" in t            # ANTI_AI_SKIN


def test_template_has_garment_fidelity_anchor():
    from scripts.pipeline.style_learner import cluster_slots  # noqa
    """技能包 template 必须含商品保真锚定（最高优先级声明+逐项复刻+禁止添加图案）。"""
    slots = cluster_slots([
        {"type": "场景种草图", "composition": "中景，背景城市街道虚化",
         "lighting": "自然光", "pose": "站立", "framing": "中景",
         "input_deps": ["flat", "model"]},
    ])
    t = slots[0]["template"]
    assert "第一张参考图是商品平铺图" in t
    assert "严禁添加" in t and "字体颜色" in t


def test_style_content_separation():
    """构图描述不携带样例特有内容（道具/印花）——由 VLM prompt 保证，
    聚合层兜底过滤：黑轿车/游船/鸡尾酒等具体物件词不入 template。"""
    from scripts.pipeline.style_learner import cluster_slots  # noqa
    slots = cluster_slots([
        {"type": "场景种草图",
         "composition": "中景，背景为游船外的水面与城市建筑虚化",
         "lighting": "自然散射光", "pose": "扶围栏", "framing": "中景",
         "input_deps": ["flat", "model"]},
    ])
    assert "游船" not in slots[0]["template"]
