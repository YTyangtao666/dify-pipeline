"""8 屏「视觉逼单」详情页故事板：结构驱动生图，替代简单风格轮播。

方法论来源：data/detail_page_method.md
核心公式：用户疑问 → 页面任务 → 产品卖点 → 视觉证据 → 购买理由。
"""
from __future__ import annotations

# 8 屏通用结构（第 7 屏按类目特化）
EIGHT_SCREENS = [
    {"no": 1, "name": "首屏定位", "user_question": "这是什么？适合我吗？",
     "task": "一秒建立品类、对象和最大价值。", "evidence": "产品主视觉 + 对的人/场景。",
     "composition": "前景大产品 + 后景故事"},
    {"no": 2, "name": "真实痛点", "user_question": "我真的有这个问题吗？",
     "task": "让用户代入原来的麻烦。", "evidence": "真实使用场景、问题局部、旧方案的不便。",
     "composition": "电影定格"},
    {"no": 3, "name": "核心方案", "user_question": "它怎么解决？",
     "task": "尽早给出最强购买理由。", "evidence": "功能可视化、结构、效果过程、对比。",
     "composition": "对角线动势"},
    {"no": 4, "name": "场景代入", "user_question": "适合我的生活吗？",
     "task": "扩大产品的真实使用价值。", "evidence": "高频情境、人物动作、使用时刻。",
     "composition": "杂志式场景路线"},
    {"no": 5, "name": "细节证明", "user_question": "为什么它真的好用？",
     "task": "通过结构、材质、设计建立可信度。", "evidence": "超微距、拆解、局部标注、工艺镜头。",
     "composition": "超微距 + 局部放大"},
    {"no": 6, "name": "使用门槛", "user_question": "用起来麻烦吗？",
     "task": "降低学习成本和行动阻力。", "evidence": "连续动作、手部演示、S 形流程、真实操作。",
     "composition": "S 形动作路径"},
    {"no": 7, "name": "类目化信任", "user_question": "我最后还担心什么？",
     "task": "回答该品类无伤大雅的“风险”，让用户觉得自己在理性决策。",
     "evidence": "档案 / 地图 / 开箱仪式（按类目特化）。",
     "composition": "档案 / 地图 / 开箱仪式"},
    {"no": 8, "name": "决策收口", "user_question": "为什么最终选择它？",
     "task": "让用户记住并带走 3—4 个购买理由。", "evidence": "最终产品英雄图 + 已被证明过的卖点收束。",
     "composition": "全屏英雄图"},
]

# 第 7 屏类目特化表（设计原则 6）
SCREEN7_BY_CATEGORY = {
    "吸尘器": "清洗结构档案：尘杯拆卸、吸头清洗、整机水洗流程。",
    "小家电": "清洁与保养结构档案：部件拆卸、清理步骤、收纳方式。",
    "服装": "尺码档案：版型、尺码对照、洗护说明与搭配参考。",
    "女装": "尺码档案：版型、尺码对照、洗护说明与搭配参考。",
    "猫粮": "配料与储存：风味地图、配料说明、开封储存建议。",
    "宠物食品": "配料与储存：风味地图、配料说明、开封储存建议。",
    "饮料": "风味地图：口感、香气、成分与储存建议。",
    "手机": "参数档案：性能、影像、续航与售后保障。",
    "数码": "参数档案：性能、接口、续航与售后保障。",
    "护肤": "成分与适用：成分说明、肤质适配、使用方法与注意事项。",
    "母婴": "尺码选择与安全：尺码对照、材质安全、使用注意。",
    "纸品": "分装与储存：家庭分装地图、独立包装、储存建议。",
    "保温杯": "材质与保养：内胆材质、保温时长说明、清洗与保养。",
    "default": "类目专属信任档案：回答该品类用户最后的顾虑。",
}

# 每屏的负面约束（AI 不得编造的内容）
NEGATIVE_COMMON = (
    "禁止生成检测报告、认证标志、虚假参数数字、功效数字；"
    "禁止乱码文字和无意义英文；文字信息只预留版面区域。"
)


def screen7_for(category: str) -> str:
    """第 7 屏按类目特化（原则 6：每个类目的第 7 屏都不同）。"""
    for key, val in SCREEN7_BY_CATEGORY.items():
        if key != "default" and key in (category or ""):
            return val
    return SCREEN7_BY_CATEGORY["default"]


def _anchor_text(product: dict) -> str:
    """产品锚点（提示词生产系统：先锁定一致性）。"""
    title = product.get("title", "")
    desc = product.get("desc", "") or ""
    return f"{title}。{desc}".strip("。")


def build_screen_prompts(product: dict) -> list[dict]:
    """按 8 屏结构构建完整提示词列表。

    每条包含：屏号、屏名、用户问题、主结论、构图、提示词、负面约束。
    """
    anchor = _anchor_text(product)
    screens = []
    seen_comp = set()
    for s in EIGHT_SCREENS:
        comp = s["composition"]
        if comp in seen_comp:  # 保证相邻屏构图不重复（原则 7）
            comp = comp + "（换角度与景别）"
        seen_comp.add(comp)

        evidence = s["evidence"]
        if s["no"] == 7:
            evidence = screen7_for(product.get("category", "") or product.get("title", ""))

        leave_blank = ""
        if s["no"] in (1, 8):
            leave_blank = "顶部/标题区预留文案留白，便于后期排版。"

        prompt = (
            f"电商详情页第{s['no']}屏「{s['name']}」。"
            f"本屏要回答的用户问题：{s['user_question']}唯一主结论：{s['task']}。"
            f"产品锚点（全组一致，不得改变外观）：{anchor}。"
            f"构图语言：{comp}。视觉证据：{evidence}"
            f"{' ' + leave_blank if leave_blank else ''}"
            f"手机端竖版 3:4 比例，{NEGATIVE_COMMON}"
        )
        screens.append({
            "screen_no": s["no"],
            "screen_name": s["name"],
            "user_question": s["user_question"],
            "task": s["task"],
            "composition": comp,
            "prompt": prompt,
            "negative": NEGATIVE_COMMON,
        })
    return screens


def build_manifest(product: dict) -> dict:
    """生图 manifest：8 屏文件名映射。"""
    prompts = build_screen_prompts(product)
    pid = product.get("product_id", "P?")
    return {
        "product_id": pid,
        "mode": "eight-screens",
        "screens": [
            {
                "file": f"{pid}_screen{p['screen_no']}_{p['screen_name']}.png",
                "screen_no": p["screen_no"],
                "screen_name": p["screen_name"],
                "prompt": p["prompt"],
                "negative": p["negative"],
            }
            for p in prompts
        ],
    }
