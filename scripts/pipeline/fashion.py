"""女装模块：AI试穿 / SKU颜色矩阵 / 多市场变体 / 女装专属构图预设。

SHEIN 场景对齐：
- ai_tryon: 平铺图( garment ) + 模特图 → 穿着图（AI试穿核心链路）
- color_matrix: 一款多色 SKU，每色独立槽位
- market_variants: 同款按目标市场（欧美/中东/东南亚）换模特与场景
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 女装构图预设（uses: flat=服装平铺图, model=模特图, white=白底图） ──
FASHION_PRESETS: dict[str, dict] = {
    "ai_tryon": {
        "name": "AI试穿图",
        "uses": ["flat", "model"],
        "size": "3:4",
        "template": (
            "第一张参考图是{title}的平铺图，第二张是模特照片。生成模特自然穿着该服装的电商图："
            "服装的款式、版型、剪裁、图案、颜色必须与平铺图 100% 一致，不得改变衣长/袖型/领型；"
            "模特姿势自然展示服装效果，脸部保持参考图特征，棚拍质感灯光，全身构图。{top3}"
        ),
    },
    "ai_tryon_street": {
        "name": "AI试穿街拍图",
        "uses": ["flat", "model"],
        "size": "3:4",
        "template": (
            "第一张参考图是{title}的平铺图，第二张是模特照片。生成模特穿该服装的城市街拍风格电商图："
            "自然街景虚化背景，行走/回眸动态感，服装款式版型颜色与平铺图完全一致，胶片色调。{top3}"
        ),
    },
    "flat_lay": {
        "name": "平铺搭配图",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}的平铺图。生成搭配展示平铺图：服装为主体，"
            "周围搭配鞋/包/配饰（同风格），俯拍构图，浅色干净背景，杂志感排版。"
            "服装本身与参考图完全一致。{top3}"
        ),
    },
    "color_swatch": {
        "name": "SKU色卡图",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}的平铺图。生成该单品的色卡展示图：服装居中，"
            "下方一排颜色圆点示意可选颜色，浅灰背景，电商规范排版。{top3}"
        ),
    },
    "detail_fabric": {
        "name": "面料细节图",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}。生成面料细节特写：微距展示面料纹理/垂坠感/刺绣/纽扣工艺，"
            "侧逆光突出质感，浅景深。不得虚构参考图上不存在的工艺。{top3}"
        ),
    },
    "size_chart": {
        "name": "尺码表图",
        "uses": ["flat"],
        "size": "3:4",
        "template": (
            "参考图是{title}。生成尺码指南图：模特穿着示意 + 关键测量点标注线"
            "（胸围/腰围/衣长，数值区留 EDIT 占位），浅色背景，清晰专业。{top3}"
        ),
    },
}

# ── 多市场变体（SHEIN 主战场） ──
MARKET_VARIANTS: dict[str, dict] = {
    "us": {
        "name": "欧美市场",
        "model_brief": "欧美面孔模特，健康小麦肤色，自然妆容",
        "scene_brief": "洛杉矶/纽约街头感，明亮自然光，简约现代",
    },
    "me": {
        "name": "中东市场",
        "model_brief": "中东面孔模特，着装风格保守优雅，妆容精致",
        "scene_brief": "暖色调奢华室内/沙漠度假酒店感，避免暴露姿势",
    },
    "sea": {
        "name": "东南亚市场",
        "name_local": "东南亚",
        "model_brief": "东南亚面孔模特，清新妆容",
        "scene_brief": "热带绿植/海岛度假感，高饱和明亮",
    },
    "eu": {
        "name": "欧洲市场",
        "model_brief": "欧洲面孔模特，冷淡高级感妆容",
        "scene_brief": "北欧极简/巴黎街道，低饱和电影感",
    },
}


def build_fashion_prompt(preset_id: str, *, title: str,
                         top3_points: list[str] | None = None,
                         color: str = "", prompt_extra: str = "") -> str:
    """女装预设 prompt：款式一致性红线 + 卖点 + 颜色/市场注入。"""
    p = FASHION_PRESETS[preset_id]
    top3 = ""
    if top3_points:
        lines = "\n".join(f"- {t}" for t in top3_points[:3])
        top3 = f"画面需视觉可见地传达卖点：\n{lines}\n"
    base = p["template"].format(title=title, top3=top3)
    if color:
        base = f"服装颜色指定：{color}（款式版型仍以平铺图为准）。{base}"
    if prompt_extra:
        base = prompt_extra + base
    return base


def build_market_prompt(preset_id: str, *, market: str, title: str,
                        top3_points: list[str] | None = None) -> str:
    """多市场变体 prompt：注入目标市场模特与场景风格。"""
    mv = MARKET_VARIANTS[market]
    extra = f"目标市场{mv.get('name_local', mv['name'])}：模特={mv['model_brief']}；场景={mv['scene_brief']}。"
    return build_fashion_prompt(preset_id, title=title, top3_points=top3_points,
                                prompt_extra=extra)


@dataclass
class ColorSlot:
    filename: str
    prompt_extra: str
    color: str


def expand_color_matrix(product_id: str, preset: str, colors: list[str],
                        variant_hints: list[dict] | None = None) -> list[ColorSlot]:
    """SKU 颜色矩阵：一款多色 → 每色一个槽位。

    variant_hints: 可选的额外变体指令（如同色不同姿势），与 colors 等长时逐色合并。
    """
    slots = []
    for i, c in enumerate(colors):
        extra = ""
        if variant_hints and i < len(variant_hints) and variant_hints[i]:
            extra = variant_hints[i].get("extra", "")
        color_directive = f"服装颜色指定：{c}。"
        slots.append(ColorSlot(
            filename=f"{product_id}_{preset}_{c}.png",
            prompt_extra=color_directive + extra,
            color=c))
    return slots
