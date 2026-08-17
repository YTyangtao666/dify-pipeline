"""构图预设库：上传白底图/模特图后，一键按 8 种电商构图生成。

每个预设 = name（中文名）+ uses（需要的参考图类型）+ template（prompt 模板）
+ size（比例建议，对应 apimart gpt-image-2 的 size 字段）。
模板变量：{title} 商品名、{top3} Top3 卖点注入（来自 L7 selling_points）。
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "main_white": {
        "name": "白底主图（升级版）",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图中是这个商品的白底图。生成一张电商主图：纯白背景，商品居中偏右，"
            "45度角展示最能体现质感的面，柔光箱打光突出材质细节与立体感。"
            "商品：{title}。{top3}要求：商品形态、颜色、logo 与参考图 100% 一致，"
            "不得改变商品结构；光影自然，边缘干净无锯齿。"
        ),
    },
    "scene_lifestyle": {
        "name": "场景生活图",
        "uses": ["white"],
        "size": "3:2",
        "template": (
            "参考图中的商品：{title}。把它放进一个真实使用场景中（根据商品品类选择最贴合的"
            "日常生活场景），前景商品占画面 40%，背景虚化但有生活气息，自然光。"
            "{top3}商品外观必须与参考图完全一致，不得添加参考图上不存在的功能或部件。"
        ),
    },
    "model_hold": {
        "name": "模特手持图",
        "uses": ["white", "model"],
        "size": "3:4",
        "template": (
            "第一张参考图是商品白底图（{title}），第二张是模特照片。生成模特自然手持/使用该商品的"
            "电商图：模特姿势放松真实，商品在画面中清晰可辨、占比适中，衣着风格与商品调性一致，"
            "棚拍质感灯光。{top3}商品必须与白底参考图 100% 一致，模特脸部保持参考图特征。"
        ),
    },
    "detail_closeup": {
        "name": "细节特写图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图是商品：{title}。生成微距细节特写图：聚焦最能体现品质的细节"
            "（材质纹理/工艺/接口），浅景深，背景同色系渐变，商业质感布光。"
            "{top3}不得虚构参考图上不存在的细节。"
        ),
    },
    "pain_contrast": {
        "name": "痛点对比图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图商品：{title}。生成左右分屏对比图：左侧黑白灰调展示痛点场景，"
            "右侧明亮色调展示使用该商品后的解决状态，商品在右侧清晰出现。"
            "{top3}中间用箭头或 VS 分隔。商品外观与参考图一致。"
        ),
    },
    "dimension_info": {
        "name": "尺寸规格图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图商品：{title}。生成三视图尺寸标注图：正面/侧面/俯视三个角度，"
            "用干净的标注线标出关键尺寸（按常见规格估计并留 EDIT 占位），"
            "浅灰背景，工程制图风格但保持电商美感。{top3}商品形态与参考图一致。"
        ),
    },
    "gift_box": {
        "name": "礼盒场景图",
        "uses": ["white"],
        "size": "4:5",
        "template": (
            "参考图商品：{title}。生成节日礼赠场景图：商品搭配礼品盒、缎带、贺卡，"
            "暖色调布光，营造送礼氛围。{top3}商品本体与参考图完全一致，礼盒为搭配物。"
        ),
    },
    "multi_angle": {
        "name": "多角度组合图",
        "uses": ["white"],
        "size": "16:9",
        "template": (
            "参考图商品：{title}。生成一张多角度组合展示图：同一商品的正/侧/背/底 "
            "4 个视角，田字格排列，每个视角下小字标注视角名，浅色渐变背景。"
            "{top3}每个视角的形态均与参考图一致。"
        ),
    },

    # ── 套餐专用预设（B1 bundles.py 引用） ──
    "selling_point": {
        "name": "卖点主张图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图商品：{title}。生成电商卖点主张图：商品居中放大占60%画面，"
            "用视觉语言（对比/示意/道具）传达核心卖点，背景纯色块或渐变，"
            "商业摄影质感。{top3}商品外观与参考图 100% 一致。"
        ),
    },
    "trust_badge": {
        "name": "信任背书图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图商品：{title}。生成信任背书图：商品 + 认证徽章/检测报告/材质说明的组合排版，"
            "徽章留 EDIT 占位文字区，浅色专业背景。{top3}商品本体与参考图一致。"
        ),
    },
    "xhs_cover": {
        "name": "小红书封面图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。生成小红书风格封面：明亮胶片色调，商品置于生活场景中，"
            "画面留出顶部标题文字区（不要生成文字），柔和自然光，氛围感强。{top3}"
        ),
    },
    "ab_hook": {
        "name": "投放钩子图",
        "uses": ["white"],
        "size": "1:1",
        "template": (
            "参考图商品：{title}。生成信息流广告图：强视觉冲击构图，商品为绝对主角，"
            "高对比配色，画面下 1/3 留白作文案区（不要生成文字）。{top3}"
        ),
    },
    "screen_positioning": {
        "name": "首屏定位图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页首屏：商品居中特写+品类定位氛围，"
            "大面积留白供标题，质感布光。{top3}商品与参考图一致。"
        ),
    },
    "screen_pain": {
        "name": "痛点场景图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页痛点屏：分屏对比，左侧灰暗痛点场景，"
            "右侧本品解决方案明亮呈现。{top3}"
        ),
    },
    "screen_solution": {
        "name": "方案展示图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页方案屏：商品结构分解/使用步骤示意，"
            "工程美学排版，标注线留 EDIT 占位。{top3}"
        ),
    },
    "screen_proof": {
        "name": "效果证据图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页证据屏：效果对比/数据可视化元素（温度曲线/时间轴类示意），"
            "浅色背景专业感。{top3}"
        ),
    },
    "screen_urgency": {
        "name": "促销逼单图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页促销屏：商品+促销氛围（丝带/爆炸贴位置留白），"
            "暖色调刺激决策，价格区留白。{top3}"
        ),
    },
    "screen_close": {
        "name": "决策收口图",
        "uses": ["white"],
        "size": "3:4",
        "template": (
            "参考图商品：{title}。详情页收口屏：商品全家福+保障图标排（留白占位），"
            "收束视觉，稳定信任感。{top3}"
        ),
    },
}


def list_presets() -> list[str]:
    return sorted(PRESETS.keys())


def build_prompt(preset_id: str, *, title: str, top3_points: list[str] | None = None) -> str:
    """组装构图 prompt：注入商品名与 Top3 卖点（有 L7 数据时）。"""
    p = PRESETS[preset_id]
    top3 = ""
    if top3_points:
        lines = "\n".join(f"- {t}" for t in top3_points[:3])
        top3 = f"画面需视觉可见地传达以下卖点（通过场景/构图/道具，不是文字堆砌）：\n{lines}\n"
    return p["template"].format(title=title, top3=top3)


def pick_presets(preset_ids: list[str]) -> list[dict]:
    """选中预设的元信息列表（前端卡片用）。"""
    return [{"preset_id": pid, **{k: v for k, v in PRESETS[pid].items() if k != "template"}}
            for pid in preset_ids if pid in PRESETS]
