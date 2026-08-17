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

    # 三段式双锚定：00A 商品标准特写（商品锚）+ 00B 模特三视图（模特锚）。
    # 00A: 以平铺图为参考、最强商品约束、只生成一次，商品颜色/印花向同一张图收敛。
    # 00B: 模特穿该商品的正/侧/背三视图——单图同时锁「人+货」绑定关系。
    anchor_a = out_dir / f"{plan.product_id}_00A_商品标准特写.png"
    anchor_b = out_dir / f"{plan.product_id}_00B_模特三视图.png"
    has_model_asset = _has_model_asset(plan.product_id)
    if plan.bundle_id.startswith("skill_"):
        if not anchor_a.exists():
            try:
                asyncio.run(_gen_product_anchor(cfg, plan, anchor_a))
                generated.append(str(anchor_a))
                print(f"  ✓ [00A] 商品标准特写 → {anchor_a.name}")
            except Exception as e:  # noqa: BLE001
                print(f"  ! [00A] 商品标准特写失败(不阻塞槽位): {str(e)[:120]}")
                anchor_a = None
        if has_model_asset and not anchor_b.exists():
            try:
                asyncio.run(_gen_model_sheet(cfg, plan, anchor_b, anchor_a))
                generated.append(str(anchor_b))
                print(f"  ✓ [00B] 模特三视图 → {anchor_b.name}")
            except Exception as e:  # noqa: BLE001
                print(f"  ! [00B] 模特三视图失败(不阻塞槽位): {str(e)[:120]}")
                anchor_b = None

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
            r = asyncio.run(_gen_with_client(cfg, plan, slot, out_path,
                                              anchor_a=anchor_a, anchor_b=anchor_b))
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
                           anchor_a: Path | None = None,
                           anchor_b: Path | None = None) -> GenResult:
    """单槽位生成：独立事件循环内的 client 生命周期（避免跨 loop 复用）。"""
    from . import compose as compose_lib
    prompt = _build_slot_prompt(plan, slot, compose_lib)
    refs = _slot_refs(plan, slot)
    uses_model = _slot_uses_model(plan, slot)
    if uses_model and anchor_a is not None and anchor_a.exists() \
            and anchor_b is not None and anchor_b.exists():
        # 模特槽位：双锚注入——[商品锚, 模特锚]，恰好两张、按位置声明职责
        refs = [anchor_a, anchor_b]
    elif anchor_a is not None and anchor_a.exists():
        # 商品槽位/降级：只注入商品锚
        refs = [anchor_a] + refs
    async with build_client(cfg) as client:
        return await generate_image(cfg, prompt, out_path,
                                    size=slot.size, interval=1.0,
                                    client=client, reference_images=refs)


def _has_model_asset(pid: str) -> bool:
    d = Path("data/assets") / pid
    if not d.exists():
        return False
    return bool(list(d.glob("model_*")) or list(d.glob("onbody_*")))


def _slot_uses_model(plan: BundlePlan, slot) -> bool:
    """槽位是否使用模特素材（uses 含 model）。"""
    import json as _json
    from .bundles import get_bundle
    if plan.bundle_id.startswith("skill_"):
        skill_id = plan.bundle_id[len("skill_"):]
        pack_f = Path(__file__).resolve().parent.parent.parent / "data" / "skills" / f"{skill_id}.json"
        try:
            pack = _json.loads(pack_f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pack = None
        if pack is not None:
            slot_def = next((s for s in pack["slots"] if s["pos"] == slot.pos), None)
            return bool(slot_def and "model" in (slot_def.get("input_deps") or []))
    # 技能包不可读时回退：参考图池里是否有模特素材注入
    refs = _slot_refs(plan, slot)
    return any(("model_" in str(r) or "onbody_" in str(r)) for r in refs)
    b = get_bundle(plan.bundle_id)
    slot_def = next((s for s in b["slots"] if s["pos"] == slot.pos and s["role"] == slot.role), None)
    return bool(slot_def and "model" in (slot_def.get("uses") or []))


async def _gen_model_sheet(cfg: Config, plan: BundlePlan, out_path: Path,
                           anchor_a: Path | None) -> GenResult:
    """模特三视图：模特穿着该商品的正/侧/背三视图并排，纯白背景。
    单图同时锁「人+货」绑定：面部/发型/肤色/身材跟 model 素材，服装跟商品锚/平铺图。"""
    assets_dir = Path("data/assets") / plan.product_id
    model_ref = None
    for kind in ("model", "onbody"):
        pool = sorted(assets_dir.glob(f"{kind}_*")) if assets_dir.exists() else []
        if pool:
            model_ref = pool[0]
            break
    if model_ref is None:
        raise FileNotFoundError("无模特素材, 跳过三视图")
    flat_ref = None
    for kind in ("flat", "white"):
        pool = sorted(assets_dir.glob(f"{kind}_*")) if assets_dir.exists() else []
        if pool:
            flat_ref = pool[0]
            break
    prompt = (
        "服装模特三视图设定图，纯白摄影棚背景，单张图横排三个全身像："
        "左=正面、中=侧面、右=背面。"
        "第一张参考图是模特原始照片：三个视图的模特面部、五官、发型发色、肤色、身材比例"
        "必须与之 100% 一致——同一个人，严禁换人/换人种/改发型。"
        "模特穿着指定商品服装：服装的颜色、印花图案、印花文字与字体颜色、版型、衣长、袖型"
        "与商品参考图逐项完全复刻，印花文字逐字母一致，严禁添加不存在的图案或装饰。"
        "三视图姿态：自然直立、双臂自然下垂、面部中性表情、不遮挡服装。"
        "真实摄影质感，胶片颗粒感，禁止塑料感皮肤与 AI 精修感。"
    )
    refs = [model_ref]
    if anchor_a is not None and anchor_a.exists():
        refs.append(anchor_a)
    elif flat_ref is not None:
        refs.append(flat_ref)
    async with build_client(cfg) as client:
        return await generate_image(cfg, prompt, out_path,
                                    size="4:3", interval=1.0,
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
