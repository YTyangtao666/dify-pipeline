"""批量引擎：Bundle 执行器——逐槽位生成、manifest 断点、失败可单跑重试。

设计：
- run_bundle(plan) 按 plan.slots 顺序执行（gpt-image-2 为异步任务模式，
  generate_image 内部已含提交/轮询；引擎层不再自建线程池——串行已够快：
  单张端到端 ~35s，5 张包 ~3 分钟，符合电商批量场景）。
- manifest.json 落在 bundle 输出目录，记录 generated/failed/skipped。
- retry_failed=True：读旧 manifest，只重跑 failed 槽位，成功项沿用。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from .bundles import BundlePlan
from .config import Config
from .imagegen import GenResult, build_client, generate_image  # noqa: F401


def run_bundle(plan: BundlePlan, *, out_dir: Path,
               retry_failed: bool = False,
               on_progress=None) -> dict:
    """执行套餐。返回 manifest dict（同时落盘）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    mf_path = out_dir / "manifest.json"

    prev = {"generated": [], "failed": [], "skipped": []}
    if retry_failed and mf_path.exists():
        try:
            prev = json.loads(mf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev = {"generated": [], "failed": [], "skipped": []}
    prev_generated = {Path(p).name for p in prev.get("generated", [])}
    prev_failed = {f.get("filename", "") for f in prev.get("failed", [])}

    cfg = Config.from_env()
    generated: list[str] = list(prev.get("generated", []))
    failed: list[dict] = []
    skipped = 0
    t0 = time.time()

    # 两段式：先生成「商品标准特写」——以平铺/白底图为参考、最强商品约束、
    # 只生成一次；后续所有槽位将其注入参考图首位，商品颜色/印花向同一张图收敛。
    anchor_name = f"{plan.product_id}_00_商品标准特写.png"
    anchor_path = out_dir / anchor_name
    if plan.bundle_id.startswith("skill_") and not anchor_path.exists():
        try:
            asyncio.run(_gen_product_anchor(cfg, plan, anchor_path))
            generated.append(str(anchor_path))
            print(f"  ✓ [00] 商品标准特写 → {anchor_name}")
        except Exception as e:  # noqa: BLE001
            print(f"  ! [00] 商品标准特写失败(不阻塞槽位): {str(e)[:120]}")
            anchor_path = None

    for slot in plan.slots:
        if not slot.runnable:
            skipped += 1
            continue
        if retry_failed and slot.filename in prev_generated:
            continue  # 断点续跑：成功的跳过
        if not retry_failed and slot.filename in prev_generated and prev_failed:
            pass  # 正常模式不读旧 manifest，直接生成
        out_path = out_dir / slot.filename
        try:
            r = asyncio.run(_gen_with_client(cfg, plan, slot, out_path, anchor=anchor_path))
            generated.append(str(out_path))
            print(f"  ✓ [{slot.pos}] {slot.role} → {slot.filename}")
            if on_progress:
                on_progress("ok", slot)
        except Exception as e:  # noqa: BLE001
            failed.append({"filename": slot.filename, "role": slot.role,
                           "error": str(e)[:200]})
            print(f"  ✗ [{slot.pos}] {slot.role}: {str(e)[:120]}")
            if on_progress:
                on_progress("failed", slot)

    manifest = {
        "bundle_id": plan.bundle_id,
        "product_id": plan.product_id,
        "generated": generated,
        "failed": failed,
        "summary": {
            "ok": len(generated),
            "failed": len(failed),
            "skipped": skipped,
            "elapsed_sec": round(time.time() - t0, 1),
        },
    }
    if retry_failed:
        manifest["summary"]["skipped"] = prev.get("summary", {}).get("skipped", 0) + skipped
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


async def _gen_with_client(cfg: Config, plan: BundlePlan, slot, out_path: Path, *,
                           anchor: Path | None = None) -> GenResult:
    """单槽位生成：独立事件循环内的 client 生命周期（避免跨 loop 复用）。"""
    from . import compose as compose_lib
    prompt = _build_slot_prompt(plan, slot, compose_lib)
    refs = _slot_refs(plan, slot)
    if anchor is not None and anchor.exists():
        refs = [anchor] + refs
    async with build_client(cfg) as client:
        return await generate_image(cfg, prompt, out_path,
                                    size=slot.size, interval=1.0,
                                    client=client, reference_images=refs)


async def _gen_product_anchor(cfg: Config, plan: BundlePlan, out_path: Path) -> GenResult:
    """商品标准特写：平铺/白底图参考 + 最强商品保真约束。"""
    assets_dir = Path("data/assets") / plan.product_id
    ref = None
    for kind in ("flat", "white", "model", "onbody"):
        pool = sorted(assets_dir.glob(f"{kind}_*")) if assets_dir.exists() else []
        if pool:
            ref = pool[0]
            break
    prompt = (
        "电商商品标准特写图，纯白背景。"
        "第一张参考图是商品本体平铺图：商品颜色、印花图案、印花文字内容与字体颜色、"
        "版型、衣长、袖型、每一处细节逐项完全复刻，印花文字逐字母一致，"
        "严禁添加参考图上不存在的任何图案、装饰或文字。"
        "正面完整呈现商品，无模特、无场景，构图居中，商品占画面主体。"
    )
    refs = [ref] if ref else []
    async with build_client(cfg) as client:
        return await generate_image(cfg, prompt, out_path,
                                    size="3:4", interval=1.0,
                                    client=client, reference_images=refs)


def _slot_refs(plan: BundlePlan, slot):
    """槽位参考图：按 uses 取素材（white/flat/model），按 preset 声明顺序。"""
    import json as _json
    from .bundles import get_bundle
    from . import compose as compose_lib
    if plan.bundle_id.startswith("skill_"):
        # 技能包槽位：preset 编码 "skill:{skill_id}:{pos}" → 从技能包 JSON 读 input_deps
        skill_id = plan.bundle_id[len("skill_"):]
        pack_f = Path(__file__).resolve().parent.parent.parent / "data" / "skills" / f"{skill_id}.json"
        pack = _json.loads(pack_f.read_text(encoding="utf-8"))
        slot_def = next((s for s in pack["slots"] if s["pos"] == slot.pos), None)
        b = {"slots": pack["slots"]}
    else:
        b = get_bundle(plan.bundle_id)
        slot_def = next((s for s in b["slots"] if s["pos"] == slot.pos and s["role"] == slot.role), None)
    # uses 来源：bundle slot 定义 > fashion/compose 预设声明
    uses = (slot_def or {}).get("uses") or _preset_uses(slot.preset)
    assets_dir = Path("data/assets")
    d = assets_dir / plan.product_id
    pool = {}
    if d.exists():
        for kind in ("white", "flat", "model"):
            pool[kind] = sorted(d.glob(f"{kind}_*"))
    refs = []
    for kind in uses:
        if pool.get(kind):
            refs.append(pool[kind][0])
    return refs


def _preset_uses(preset_id: str) -> list[str]:
    """从 fashion/compose 预设反查 uses。"""
    from . import compose as compose_lib
    for lib in (fashion_lib(), compose_lib):
        if preset_id in getattr(lib, "PRESETS", {}):
            return lib.PRESETS[preset_id].get("uses", ["white"])
    return ["white"]


def fashion_lib():
    from . import fashion
    return fashion


def _build_slot_prompt(plan: BundlePlan, slot, compose_lib) -> str:
    """槽位 prompt：构图模板 + 商品名 + Top3 注入 + AB 钩子。"""
    import json as _json
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent.parent
    title = plan.product_id
    pf = root / "data" / "products.json"
    if pf.exists():
        try:
            for p in _json.loads(pf.read_text(encoding="utf-8")):
                if p["product_id"] == plan.product_id:
                    title = p.get("title", title)
                    break
        except Exception:  # noqa: BLE001
            pass
    top3 = []
    sp = root / "data" / f"selling_points_{plan.product_id}.json"
    if sp.exists():
        try:
            top3 = [t["point"] for t in _json.loads(sp.read_text(encoding="utf-8")).get("top3", [])]
        except Exception:  # noqa: BLE001
            pass
    # AB 钩子注入：hook 文案里的 {pain}/{benefit} 用 Top3 数据替换
    pts = top3 or None
    from .bundles import get_bundle
    b = get_bundle(plan.bundle_id)
    slot_def = next((s for s in b["slots"] if s["pos"] == slot.pos and s["role"] == slot.role), {})
    if slot.hook and top3:
        sp2 = root / "data" / f"selling_points_{plan.product_id}.json"
        try:
            table = _json.loads(sp2.read_text(encoding="utf-8"))
            pain = table["top3"][0].get("pain", "")
            point = table["top3"][0].get("point", "")
        except Exception:  # noqa: BLE001
            pain = point = ""
        hook = slot_def.get("hook", "").replace("{pain}", pain[:12]).replace("{benefit}", point[:10])
    else:
        hook = slot.hook
    from . import fashion as fashion_lib
    if slot.preset in fashion_lib.FASHION_PRESETS:
        # 女装预设：market 变体优先
        market = (slot_def or {}).get("market") if slot_def else None
        if market and market in fashion_lib.MARKET_VARIANTS:
            prompt = fashion_lib.build_market_prompt(slot.preset, market=market,
                                                      title=title, top3_points=pts)
        else:
            prompt = fashion_lib.build_fashion_prompt(slot.preset, title=title, top3_points=pts)
    else:
        prompt = compose_lib.build_prompt(slot.preset, title=title, top3_points=pts)
    if hook:
        prompt = f"画面氛围钩子：{hook}。{prompt}"
    return prompt
