"""套餐（Bundle）：带位置语义的电商素材清单。

一个 Bundle = 一次可交付的完整素材包（如天猫主图轮播 5 张）。
每个 slot 定义：上架位置 pos、角色 role、构图 preset、比例 size、
素材依赖 uses、卖点注入 inject_top3（取 L7 Top3 卖点表第 N 条）。

ab_test 类套餐支持 variants：同一 slot 生成 N 版（文案钩子不同）供投放赛马。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# 实测：apimart gpt-image-2 @1k ≈ 0.085 credits/张；单张端到端 ≈ 35s（并发2时 ~18s/张）
CREDITS_PER_IMAGE = 0.085
SECONDS_PER_IMAGE = 18.0

BUNDLES: dict[str, dict] = {
    "tmall_main5": {
        "name": "天猫主图轮播包（5张）",
        "desc": "平台上架硬性结构：第1张白底规范，2-5 卖点递进",
        "slots": [
            {"pos": 1, "role": "白底规范图", "preset": "main_white", "size": "1:1", "uses": ["white"]},
            {"pos": 2, "role": "核心卖点图", "preset": "selling_point", "size": "1:1",
             "uses": ["white"], "inject_top3": 0},
            {"pos": 3, "role": "场景使用图", "preset": "scene_lifestyle", "size": "1:1", "uses": ["white"]},
            {"pos": 4, "role": "细节工艺图", "preset": "detail_closeup", "size": "1:1", "uses": ["white"]},
            {"pos": 5, "role": "信任背书图", "preset": "trust_badge", "size": "1:1", "uses": ["white"]},
        ],
    },
    "xhs_pack6": {
        "name": "小红书种草包（6张）",
        "desc": "3:4 竖图，生活感种草 + 模特 + 细节",
        "slots": [
            {"pos": 1, "role": "封面钩子图", "preset": "xhs_cover", "size": "3:4", "uses": ["white"], "inject_top3": 0},
            {"pos": 2, "role": "场景种草图", "preset": "scene_lifestyle", "size": "3:4", "uses": ["white"]},
            {"pos": 3, "role": "模特使用图", "preset": "model_hold", "size": "3:4", "uses": ["white", "model"]},
            {"pos": 4, "role": "细节特写图", "preset": "detail_closeup", "size": "3:4", "uses": ["white"]},
            {"pos": 5, "role": "痛点对比图", "preset": "pain_contrast", "size": "3:4", "uses": ["white"]},
            {"pos": 6, "role": "合集收官图", "preset": "multi_angle", "size": "3:4", "uses": ["white"]},
        ],
    },
    "detail_8screen": {
        "name": "详情页八屏包（8张）",
        "desc": "视觉逼单八屏结构（复用 detail_page_method 方法论）",
        "slots": [
            {"pos": i, "role": role, "preset": preset, "size": "3:4", "uses": ["white"]}
            for i, (role, preset) in enumerate([
                ("首屏定位", "screen_positioning"), ("真实痛点", "screen_pain"),
                ("核心方案", "screen_solution"), ("效果证据", "screen_proof"),
                ("信任背书", "trust_badge"), ("场景代入", "scene_lifestyle"),
                ("促销逼单", "screen_urgency"), ("决策收口", "screen_close"),
            ], 1)
        ],
    },
    "ab_test6": {
        "name": "投放赛马包（6变体）",
        "desc": "同一构图 × 6 个文案钩子——CTR 赛马素材组",
        "variants_ready": True,
        "slots": [
            {"pos": 1, "role": "钩子A-痛点直击", "preset": "ab_hook", "size": "1:1",
             "uses": ["white"], "inject_top3": 0, "hook": "还在为{pain}烦恼吗"},
            {"pos": 2, "role": "钩子B-数字冲击", "preset": "ab_hook", "size": "1:1",
             "uses": ["white"], "inject_top3": 0, "hook": "24小时{benefit}的秘密"},
            {"pos": 3, "role": "钩子C-对比反差", "preset": "pain_contrast", "size": "1:1", "uses": ["white"]},
            {"pos": 4, "role": "钩子D-信任状", "preset": "trust_badge", "size": "1:1", "uses": ["white"]},
            {"pos": 5, "role": "钩子E-场景共鸣", "preset": "scene_lifestyle", "size": "1:1", "uses": ["white"]},
            {"pos": 6, "role": "钩子F-价格锚点", "preset": "selling_point", "size": "1:1",
             "uses": ["white"], "inject_top3": 2},
        ],
    },
    "shein_launch": {
        "name": "SHEIN上架包（8张）",
        "desc": "女装跨境全套：AI试穿×2 + 街拍 + 平铺搭配 + 色卡 + 面料 + 尺码 + 场景",
        "slots": [
            {"pos": 1, "role": "试穿主图", "preset": "ai_tryon", "size": "3:4", "uses": ["flat", "model"]},
            {"pos": 2, "role": "试穿街拍", "preset": "ai_tryon_street", "size": "3:4", "uses": ["flat", "model"]},
            {"pos": 3, "role": "平铺搭配", "preset": "flat_lay", "size": "1:1", "uses": ["flat"]},
            {"pos": 4, "role": "SKU色卡", "preset": "color_swatch", "size": "1:1", "uses": ["flat"]},
            {"pos": 5, "role": "面料细节", "preset": "detail_fabric", "size": "1:1", "uses": ["flat"]},
            {"pos": 6, "role": "尺码指南", "preset": "size_chart", "size": "3:4", "uses": ["flat"]},
            {"pos": 7, "role": "场景种草", "preset": "ai_tryon", "size": "3:4", "uses": ["flat", "model"],
             "market": "us"},
            {"pos": 8, "role": "中东市场", "preset": "ai_tryon", "size": "3:4", "uses": ["flat", "model"],
             "market": "me"},
        ],
    },
    "full_launch": {
        "name": "全量上架包（11张）",
        "desc": "tmall_main5 + xhs_pack6 组合，一次跑齐",
        "compose": ["tmall_main5", "xhs_pack6"],
        "slots": [],
    },
}


def get_bundle(bundle_id: str) -> dict:
    if bundle_id not in BUNDLES:
        raise KeyError(f"未知套餐: {bundle_id}")
    b = BUNDLES[bundle_id]
    if b.get("compose"):
        slots = []
        for sub in b["compose"]:
            slots.extend(BUNDLES[sub]["slots"])
        return {**b, "slots": slots}
    return b


@dataclass
class SlotPlan:
    pos: int
    role: str
    preset: str
    size: str
    filename: str
    runnable: bool
    skip_reason: str = ""
    variant: int = 1
    hook: str = ""


@dataclass
class BundlePlan:
    bundle_id: str
    product_id: str
    slots: list[SlotPlan] = field(default_factory=list)
    estimated_credits: float = 0.0
    estimated_seconds: float = 0.0

    @property
    def total_runnable(self) -> int:
        return sum(1 for s in self.slots if s.runnable)


def _assets_of(pid: str, assets_dir: Path) -> dict[str, list[Path]]:
    d = assets_dir / pid
    if not d.exists():
        return {"white": [], "model": [], "flat": []}
    return {
        "white": sorted(d.glob("white_*")),
        "model": sorted(d.glob("model_*")),
        "flat": sorted(d.glob("flat_*")),
    }


def plan_bundle(pid: str, bundle_id: str, *, assets_dir: Path,
                variants: int = 1) -> BundlePlan:
    """把套餐定义 + 实际素材 → 可执行清单（缺素材槽位标注跳过原因）。"""
    b = get_bundle(bundle_id)
    assets = _assets_of(pid, assets_dir)
    n_variants = max(1, variants) if b.get("variants_ready") else 1
    slots: list[SlotPlan] = []
    for s in b["slots"]:
        missing = [k for k in s.get("uses", []) if not assets.get(k)]
        for v in range(1, n_variants + 1):
            vname = f"_v{v}" if n_variants > 1 else ""
            fname = f"{pid}_main{s['pos']}_{s['role']}{vname}.png" \
                if bundle_id == "tmall_main5" or s.get("hook") is None and bundle_id == "full_launch" \
                else f"{pid}_{s['pos']:02d}_{s['role']}{vname}.png"
            if bundle_id == "tmall_main5":
                fname = f"{pid}_main{s['pos']}_{s['role']}{vname}.png"
            runnable = not missing
            reason = ""
            names = {"white": "白底图", "model": "模特图", "flat": "平铺图"}
            if not runnable:
                need = "、".join(names.get(k, k) for k in missing)
                reason = f"缺少{need}"
            slots.append(SlotPlan(pos=s["pos"], role=s["role"], preset=s["preset"],
                                  size=s["size"], filename=fname, runnable=runnable,
                                  skip_reason=reason, variant=v,
                                  hook=s.get("hook", "")))
    plan = BundlePlan(bundle_id=bundle_id, product_id=pid, slots=slots)
    n = plan.total_runnable
    plan.estimated_credits = round(n * CREDITS_PER_IMAGE, 3)
    plan.estimated_seconds = round(n * SECONDS_PER_IMAGE)
    return plan
