"""C2: 构图预设库 compose.py——白底图/模特图 → 8 种电商构图 prompt。"""
from scripts.pipeline.compose import (
    PRESETS, build_prompt, list_presets, pick_presets,
)


def test_list_presets_has_8():
    ids = list_presets()
    assert len(ids) >= 8
    assert "scene_lifestyle" in ids and "model_hold" in ids


def test_preset_schema():
    for pid, p in PRESETS.items():
        assert p["name"] and p["template"], pid
        assert "{title}" in p["template"] or "{top3}" in p["template"]


def test_build_prompt_basic():
    s = build_prompt("scene_lifestyle", title="316不锈钢保温杯")
    assert "316不锈钢保温杯" in s
    assert "参考图" in s or "白底" in s  # 图生图指令存在


def test_build_prompt_with_top3():
    top3 = ["316医用级内胆", "24小时保温"]
    s = build_prompt("model_hold", title="保温杯", top3_points=top3)
    assert "316医用级内胆" in s and "24小时保温" in s


def test_build_prompt_size_hint():
    p = PRESETS["main_white"]
    assert "size" in p  # 每个预设带尺寸建议


def test_pick_presets_subset():
    picked = pick_presets(["main_white", "scene_lifestyle"])
    assert len(picked) == 2
    assert all("preset_id" in x for x in picked)
