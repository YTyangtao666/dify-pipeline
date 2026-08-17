"""F1-F3: 女装化——AI试穿预设 + SKU颜色矩阵 + 多市场变体。"""
import pytest

from scripts.pipeline import fashion


def test_tryon_preset_exists():
    p = fashion.FASHION_PRESETS["ai_tryon"]
    assert p["uses"] == ["flat", "model"]
    assert "{title}" in p["template"]


def test_tryon_prompt_includes_garment_consistency():
    s = fashion.build_fashion_prompt("ai_tryon", title="法式碎花连衣裙")
    assert "款式" in s or "版型" in s
    assert "一致" in s


def test_color_matrix_expansion():
    """一款多色 → 每色一个生成槽位。"""
    slots = fashion.expand_color_matrix(
        product_id="D001", preset="ai_tryon",
        colors=["黑色", "杏色", "雾霾蓝"],
        variant_hints=[{"color": "黑色"}] * 3)
    assert len(slots) == 3
    assert slots[0].filename == "D001_ai_tryon_黑色.png"
    assert "黑色" in slots[0].prompt_extra


def test_market_variants():
    """同款换市场：欧美/中东/东南亚 模特与场景风格变体。"""
    vs = fashion.MARKET_VARIANTS
    assert {"us", "me", "sea"} <= set(vs.keys())
    for k, v in vs.items():
        assert v["model_brief"] and v["scene_brief"]


def test_market_variant_prompt():
    s = fashion.build_market_prompt("ai_tryon", market="me", title="长裙")
    assert "中东" in s or vs_in(s)
    assert "款式" in s


def vs_in(s):
    return "保守" in s or "长袍" in s


def test_fashion_bundle_slots():
    """shein_launch 套餐槽位结构。"""
    from scripts.pipeline.bundles import BUNDLES, get_bundle
    assert "shein_launch" in BUNDLES
    b = get_bundle("shein_launch")
    assert len(b["slots"]) >= 6
    # 必含试穿与色卡
    presets = {s["preset"] for s in b["slots"]}
    assert "ai_tryon" in presets
    assert "color_swatch" in presets
