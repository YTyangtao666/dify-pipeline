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
    # ── SHEIN 官方素材结构提炼（对标 shein-tshirt 9 图金标准）──
    "model_front": {
        "name": "模特正面上身图",
        "uses": ["flat", "model"],
        "size": "3:4",
        "template": (
            "参考平铺图为{title}。生成真人实拍感上身图：模特半身出镜，"
            "顶部柔和主光+前方补光，姿势自然（单手轻抚头发/微侧身），"
            "背景虚化日常生活场景（大光圈散景），胸到腰中景，"
            "服装上的印花文字必须清晰完整无变形。胶片质感，不要棚拍摆拍感。{top3}"
        ),
    },
    "street_night": {
        "name": "夜景街拍图",
        "uses": ["flat", "model"],
        "size": "3:4",
        "template": (
            "参考平铺图为{title}。夜间街拍：顶部柔和光线照亮人物+前方补光，"
            "模特动态姿势（手举过头顶/走动回眸），背景城市夜景大光圈虚化（车灯/街灯散景），"
            "半身特写，服装印花文字清晰可读。夜间人像摄影质感。{top3}"
        ),
    },
    "white_front": {
        "name": "白底正面平铺图",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}。生成纯白背景平铺图：服装正面居中，"
            "均匀漫射光无阴影，面料纹理与印花文字清晰，电商规范白底图。{top3}"
        ),
    },
    "white_back": {
        "name": "白底背面平铺图",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}。生成纯白背景平铺图：展示服装背面，居中，"
            "均匀漫射光，背面剪裁与缝线清晰。{top3}"
        ),
    },
    "detail_grid4": {
        "name": "细节四宫格",
        "uses": ["flat"],
        "size": "1:1",
        "template": (
            "参考图是{title}。生成细节四宫格：领口罗纹双针缝/袖口卷边/下摆走线/面料纹理"
            "四个微距特写，2x2排列，柔光突出缝线工艺，电商品质展示图。{top3}"
        ),
    },
    "overhead_casual": {
        "name": "俯拍日常图",
        "uses": ["flat", "model"],
        "size": "3:4",
        "template": (
            "参考平铺图为{title}。高角度俯拍模特腰部以上，模特自然低头或侧脸，"
            "服装文字居中清晰，背景虚化日常环境（咖啡馆/街道），生活感真实。{top3}"
        ),
    },
}



# ── 模特质量红线（用户验收标准：脸要一致+无AI味+身材极品） ──
MODEL_ANCHOR = (
    "若参考图最后一张是模特三视图设定图（横排正/侧/背三视图）：模特面部、五官、发型发色、"
    "肤色、身材比例必须与之 100% 一致——同一个人，严禁换人/换人种/改发型。服装的样式、"
    "颜色、印花必须与商品参考图（第一张）完全一致，不得跟随三视图之外的创新。"
    "若无三视图参考，则与含模特人像的参考图保持面部一致，纯商品图不是模特参考。"
)
BODY_DIRECTIVE = (
    "模特身材要求：高挑纤细、大长腿、腰臀比黄金比例、肩颈线条优雅、体态挺拔，"
    "时尚大片级身材，具有视觉冲击力。"
)
ANTI_AI_SKIN = (
    "真实摄影质感：保留皮肤自然纹理与毛孔、发丝根根分明，胶片颗粒感，"
    "禁止塑料感皮肤、过度磨皮、AI精修感。"
)


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
                         color: str = "", prompt_extra: str = "",
                         anchor_model: bool = True) -> str:
    """女装预设 prompt：款式一致性红线 + 卖点 + 颜色/市场注入。

    anchor_model=True（默认）：注入模特身份锚定+身材+反AI味三条红线，
    保证跨槽位同一模特、极品身材、真实质感。market 变体走 build_market_prompt
    会关掉面部锚定（按市场换人是特性）但保留身材与质感红线。
    """
    p = FASHION_PRESETS[preset_id]
    top3 = ""
    if top3_points:
        lines = "\n".join(f"- {t}" for t in top3_points[:3])
        top3 = f"画面需视觉可见地传达卖点：\n{lines}\n"
    base = p["template"].format(title=title, top3=top3)
    has_model = "model" in p.get("uses", [])
    quality = ""
    if has_model:
        quality = "\n" + BODY_DIRECTIVE + "\n" + ANTI_AI_SKIN
        if anchor_model:
            quality = "\n" + MODEL_ANCHOR + quality
    if color:
        base = f"服装颜色指定：{color}（款式版型仍以平铺图为准）。{base}"
    if prompt_extra:
        base = prompt_extra + base
    return base + quality


def build_market_prompt(preset_id: str, *, market: str, title: str,
                        top3_points: list[str] | None = None) -> str:
    """多市场变体 prompt：注入目标市场模特与场景风格。

    注意：market 变体不复用参考模特的面部——按目标市场人种重新生成模特，
    否则「保持模特特征」红线会压过市场指令（实测踩坑）。
    """
    mv = MARKET_VARIANTS[market]
    extra = (f"目标市场{mv.get('name_local', mv['name'])}：模特={mv['model_brief']}；"
             f"场景={mv['scene_brief']}。模特面部不要求与参考模特一致——"
             f"按目标市场人种重新生成；但服装款式必须与平铺参考图完全一致。")
    return build_fashion_prompt(preset_id, title=title, top3_points=top3_points,
                                prompt_extra=extra, anchor_model=False)


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
