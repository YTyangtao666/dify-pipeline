"""风格学习器：样例电商图集 → 可复用技能包（Style Skill Pack）。

三步：
  1. 逐图 VLM 逆向分析（type/composition/lighting/pose/framing）→ prompt_hint
  2. 聚类成槽位：同类型合并取共性，跨类型分槽，自动推断 input_deps
  3. 固化为技能包 JSON（数据非代码——新风格零代码接入）

服装类槽位自动附加三红线（MODEL_ANCHOR / BODY_DIRECTIVE / ANTI_AI_SKIN）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .fashion import ANTI_AI_SKIN, BODY_DIRECTIVE, MODEL_ANCHOR

DEP_RULES = [
    (re.compile(r"模特|上身|街拍|试穿|场景种草"), ["flat", "model"]),
    (re.compile(r"白底|平铺|细节|面料|色卡|尺码"), ["flat"]),
    (re.compile(r"主图白底"), ["white"]),
]


def build_prompt_hint(analysis: dict) -> str:
    """单图分析 → 一段可复用的构图指令。"""
    parts = []
    if analysis.get("framing"):
        parts.append(analysis["framing"])
    if analysis.get("composition"):
        parts.append(analysis["composition"])
    if analysis.get("lighting"):
        parts.append(analysis["lighting"])
    if analysis.get("pose"):
        parts.append(f"姿势：{analysis['pose']}")
    return "，".join(parts)


def infer_deps(analysis: dict) -> list[str]:
    """从图类型推断生成它需要的输入素材。"""
    t = analysis.get("type", "")
    for pat, deps in DEP_RULES:
        if pat.search(t):
            return deps
    return ["flat"]


# 样例特有内容兜底过滤（VLM prompt 已要求忽略，聚合层再兜一层）
_PROPS_BLOCKLIST = ["游船", "鸡尾酒", "轿车", "栏杆", "围栏", "甜点", "咖啡杯", "海报"]


def _strip_props(text: str) -> str:
    for w in _PROPS_BLOCKLIST:
        text = text.replace(w, "")
    return text


def cluster_slots(analyses: list[dict]) -> list[dict]:
    """同类型合并取共性，跨类型分槽位。"""
    by_type: dict[str, list[dict]] = {}
    for a in analyses:
        by_type.setdefault(a.get("type", "未分类"), []).append(a)

    slots = []
    for role, group in by_type.items():
        comps = "；".join(dict.fromkeys(_strip_props(a.get("composition", "")) for a in group if a.get("composition")))
        lights = "；".join(dict.fromkeys(a.get("lighting", "") for a in group if a.get("lighting")))
        poses = "；".join(dict.fromkeys(_strip_props(a.get("pose", "")) for a in group if a.get("pose")))
        framings = "；".join(dict.fromkeys(a.get("framing", "") for a in group if a.get("framing")))
        deps = group[0].get("input_deps") or infer_deps(group[0])
        garment_anchor = (
            "【商品保真·最高优先级】第一张参考图是商品平铺图：服装的颜色、印花内容、印花文字、"
            "字体颜色、版型、衣长、袖型必须与平铺图逐项完全复刻——印花文字逐字母一致，"
            "印花颜色（含字体色）不得改变，严禁添加平铺图上不存在的任何图案或装饰。"
        )
        template = (
            f"生成{role}：{framings}。构图：{comps}。灯光：{lights}。"
            + (f"{poses}。" if poses else "")
            + f"{garment_anchor}商品：{{title}}。"
            + ("画面需传达：{selling_points}" if "model" in deps else "")
        )
        if "model" in deps:
            template += f"\n{MODEL_ANCHOR}\n{BODY_DIRECTIVE}\n{ANTI_AI_SKIN}"
        slots.append({
            "pos": len(slots) + 1,
            "role": role,
            "size": group[0].get("size", "3:4" if "model" in deps else "1:1"),
            "input_deps": deps,
            "template": template,
        })
    return slots


def make_skill_pack(skill_id: str, name: str, slots: list[dict],
                    *, sample_dir: Path | None = None,
                    title_hint: str = "") -> dict:
    """组装技能包（含质量门槛与溯源信息）。"""
    return {
        "skill_id": skill_id,
        "name": name,
        "title_hint": title_hint,
        "created": datetime.now().isoformat(timespec="seconds"),
        "learned_from": str(sample_dir) if sample_dir else "",
        "slots": slots,
        "quality_bar": {"min_usable_rate": 80},
    }


def save_skill_pack(pack: dict, *, data_dir: Path) -> Path:
    validate_skill_pack(pack)
    d = Path(data_dir) / "skills"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{pack['skill_id']}.json"
    p.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def validate_skill_pack(pack: dict) -> None:
    """技能包必须：有 skill_id、≥1 槽位、每槽位有 template 与 input_deps。"""
    if not pack.get("skill_id"):
        raise ValueError("技能包缺 skill_id")
    slots = pack.get("slots") or []
    if not slots:
        raise ValueError("技能包无槽位")
    for s in slots:
        if not s.get("template"):
            raise ValueError(f"槽位 {s.get('role')} 缺 template")
        if not s.get("input_deps"):
            raise ValueError(f"槽位 {s.get('role')} 缺 input_deps")


def load_skill_pack(skill_id: str, *, data_dir: Path) -> dict:
    p = Path(data_dir) / "skills" / f"{skill_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"技能包不存在: {skill_id}")
    pack = json.loads(p.read_text(encoding="utf-8"))
    validate_skill_pack(pack)
    return pack


# ── VLM 逆向分析（真实链路：gemini-2.5-flash @ apimart relay 或直连代理） ──
ANALYZE_PROMPT = (
    "分析这张电商素材图的可复用【风格要素】。注意：只提取可跨商品复用的构图/灯光/姿势/景别，"
    "忽略该样例特有的商品内容（印花文字/颜色/图案）、具体环境物件（车/船/杯子等道具）和模特长相。"
    "只输出 JSON（无其他文字）："
    '{"type": "图类型(如:模特正面生活图/白底平铺图/细节特写图/场景种草图/夜景街拍图)",'
    ' "composition": "构图(景别+主体位置+背景虚化处理,环境只写大类如城市街道/室内,不写具体物件)",'
    ' "lighting": "灯光(方向+质感)",'
    ' "pose": "模特姿势(通用描述,无模特则空串)",'
    ' "framing": "取景范围(如胸到腰中景)"}'
)


async def analyze_image_vlm(image_path: Path) -> dict:
    """单图 VLM 逆向分析。走主 VLM 配置（含兜底）。"""
    import base64 as _b64
    import httpx
    from .config import Config
    cfg = Config.from_env()
    b64 = _b64.b64encode(Path(image_path).read_bytes()).decode()
    payload = {"model": cfg.vlm_model, "stream": False, "max_tokens": 2000,
               "temperature": 0,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": ANALYZE_PROMPT},
                   {"type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    async with httpx.AsyncClient(base_url=cfg.base_url,
                                 headers={"Authorization": f"Bearer {cfg.api_key}"},
                                 proxy=cfg.proxy, timeout=120.0) as client:
        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    from .evaluator import extract_json
    data = extract_json(content)
    if not data:
        raise RuntimeError(f"VLM 分析输出无法解析: {content[:120]}")
    return data


def learn_from_dir(sample_dir: Path, *, skill_id: str, name: str,
                   data_dir: Path) -> dict:
    """同步入口：目录下全部图片 → 逐图分析 → 聚合 → 技能包落盘。"""
    import asyncio
    imgs = sorted([p for p in Path(sample_dir).iterdir()
                   if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
    if not imgs:
        raise ValueError(f"{sample_dir} 下没有图片")
    analyses = [asyncio.run(analyze_image_vlm(p)) for p in imgs]
    slots = cluster_slots(analyses)
    pack = make_skill_pack(skill_id, name, slots, sample_dir=sample_dir)
    save_skill_pack(pack, data_dir=data_dir)
    return pack
