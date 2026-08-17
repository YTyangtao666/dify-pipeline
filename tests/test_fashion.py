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

def test_shein_official_presets():
    """SHEIN 官方素材结构（shein-tshirt 9图）提炼的预设齐全。"""
    for pid in ["model_front", "street_night", "white_front", "white_back",
                "detail_grid4", "overhead_casual"]:
        assert pid in fashion.FASHION_PRESETS, pid
        assert "{title}" in fashion.FASHION_PRESETS[pid]["template"]


def test_shein_tshirt_bundle():
    from scripts.pipeline.bundles import BUNDLES, get_bundle
    assert "shein_tshirt" in BUNDLES
    b = get_bundle("shein_tshirt")
    assert len(b["slots"]) == 8


def test_model_anchor_injected_by_default():
    from scripts.pipeline.fashion import build_fashion_prompt, build_market_prompt  # noqa
    """模特图预设默认注入:身份锚定+身材红线+反AI味。"""
    s = build_fashion_prompt("model_front", title="T恤")
    assert "100% 一致" in s          # 面部锚定
    assert "大长腿" in s              # 身材红线
    assert "毛孔" in s                # 反AI味


def test_market_variant_keeps_body_but_no_anchor():
    from scripts.pipeline.fashion import build_market_prompt  # noqa
    """market 变体:保留身材+质感,但面部不锚定(换市场人种)。"""
    s = build_market_prompt("ai_tryon", market="us", title="dress")
    assert "大长腿" in s and "毛孔" in s
    assert "与第二张参考图（模特照片）100% 一致" not in s


def test_non_model_preset_no_anchor():
    from scripts.pipeline.fashion import build_fashion_prompt  # noqa
    """无模特预设(白底平铺)不注入面部锚定(无关且干扰)。"""
    s = build_fashion_prompt("white_front", title="T恤")
    assert "100% 一致" not in s
    assert "大长腿" not in s  # 无模特也无身材指令
