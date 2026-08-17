"""B2: 批量引擎——队列 + 并发 + manifest 断点 + 单槽位重跑。"""
import pytest

from scripts.pipeline import runner
from scripts.pipeline.bundles import BundlePlan, SlotPlan


def _plan(slots_spec, tmp_path, pid="P001"):
    slots = [SlotPlan(pos=p, role=r, preset="main_white", size="1:1",
                      filename=f"{pid}_{p:02d}_{r}.png", runnable=True)
             for p, r in slots_spec]
    return BundlePlan(bundle_id="tmall_main5", product_id=pid, slots=slots)


def test_run_bundle_writes_manifest_and_images(tmp_path, monkeypatch):
    """3 槽位全部生成 → manifest 3 ok + 图片落盘。"""
    plan = _plan([(1, "a"), (2, "b"), (3, "c")], tmp_path)
    calls = []

    async def fake_gen(cfg, prompt, out_path, **kw):
        calls.append(out_path.name)
        out_path.write_bytes(b"PNG")
        from scripts.pipeline.imagegen import GenResult
        return GenResult(path=out_path, remote_url="http://x")

    monkeypatch.setattr(runner, "generate_image", fake_gen)
    result = runner.run_bundle(plan, out_dir=tmp_path / "out")
    assert result["summary"]["ok"] == 3
    assert result["summary"]["failed"] == 0
    assert len(calls) == 3
    mf = tmp_path / "out" / "manifest.json"
    assert mf.exists()
    import json
    m = json.loads(mf.read_text())
    assert len(m["generated"]) == 3


def test_failed_slot_recorded_others_continue(tmp_path, monkeypatch):
    """槽位2失败 → 1和3照常，manifest 记录 failed 原因。"""
    plan = _plan([(1, "a"), (2, "b"), (3, "c")], tmp_path)
    n = {"i": 0}

    async def fake_gen(cfg, prompt, out_path, **kw):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("quota boom")
        out_path.write_bytes(b"PNG")
        from scripts.pipeline.imagegen import GenResult
        return GenResult(path=out_path)

    monkeypatch.setattr(runner, "generate_image", fake_gen)
    result = runner.run_bundle(plan, out_dir=tmp_path / "out")
    assert result["summary"]["ok"] == 2
    assert result["summary"]["failed"] == 1
    assert "quota boom" in result["failed"][0]["error"]


def test_retry_failed_only_reruns_failed(tmp_path, monkeypatch):
    """断点重跑：只跑 manifest 里 failed 的槽位，成功的跳过。"""
    plan = _plan([(1, "a"), (2, "b")], tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    import json
    (out / "manifest.json").write_text(json.dumps({
        "bundle_id": "tmall_main5", "product_id": "P001",
        "generated": ["P001_01_a.png"], "failed": [{"filename": "P001_02_b.png", "error": "x"}],
    }, ensure_ascii=False))
    ran = []

    async def fake_gen(cfg, prompt, out_path, **kw):
        ran.append(out_path.name)
        out_path.write_bytes(b"PNG")
        from scripts.pipeline.imagegen import GenResult
        return GenResult(path=out_path)

    monkeypatch.setattr(runner, "generate_image", fake_gen)
    result = runner.run_bundle(plan, out_dir=out, retry_failed=True)
    assert ran == ["P001_02_b.png"]  # 只重跑了失败的
    assert result["summary"]["ok"] == 2  # 累计口径: 1 旧成功 + 1 新成功


def test_skipped_slots_not_attempted(tmp_path, monkeypatch):
    """plan 里 runnable=False 的槽位不发起生成。"""
    s1 = SlotPlan(pos=1, role="a", preset="main_white", size="1:1",
                  filename="x.png", runnable=True)
    s2 = SlotPlan(pos=3, role="模特", preset="model_hold", size="1:1",
                  filename="y.png", runnable=False, skip_reason="缺少模特图")
    plan = BundlePlan(bundle_id="xhs_pack6", product_id="P001", slots=[s1, s2])
    ran = []

    async def fake_gen(cfg, prompt, out_path, **kw):
        ran.append(out_path.name)
        out_path.write_bytes(b"P")
        from scripts.pipeline.imagegen import GenResult
        return GenResult(path=out_path)

    monkeypatch.setattr(runner, "generate_image", fake_gen)
    result = runner.run_bundle(plan, out_dir=tmp_path / "out")
    assert ran == ["x.png"]
    assert result["summary"]["skipped"] == 1


def test_product_anchor_generated_first_and_injected(tmp_path, monkeypatch):
    """两段式：先出商品标准特写，后续槽位把它注入参考图首位。"""
    from scripts.pipeline import runner
    from scripts.pipeline.bundles import BundlePlan, SlotPlan

    calls = []

    async def fake_gen(cfg, prompt, out_path, **kw):
        calls.append({"prompt": prompt, "refs": [str(r) for r in kw.get("reference_images", [])],
                      "out": str(out_path)})
        out_path.write_bytes(b"x")
        return None

    monkeypatch.setattr(runner, "generate_image", fake_gen)
    monkeypatch.setattr(runner, "_slot_refs", lambda plan, slot: ["/tmp/flat_1.png"])
    monkeypatch.setattr(runner, "_build_slot_prompt", lambda plan, slot, cl: f"prompt-{slot.pos}")
    # 造商品素材,供 _gen_product_anchor 找到 flat 参考图(runner 用相对路径 data/assets)
    from pathlib import Path as _Path
    assets = _Path.cwd() / "data" / "assets" / "P1"
    assets.mkdir(parents=True, exist_ok=True)
    f = assets / "flat_1.png"
    f.write_bytes(b"x")
    import pytest as _pytest

    @_pytest.fixture(autouse=True)
    def _cleanup():
        yield
        import shutil as _sh
        _sh.rmtree(assets, ignore_errors=True)

    slots = [SlotPlan(pos=1, role="白底单品图", preset="skill:s1:1", size="3:4",
                      filename="P1_01_白底单品图.png", runnable=True),
             SlotPlan(pos=2, role="街拍图", preset="skill:s1:2", size="3:4",
                      filename="P1_02_街拍图.png", runnable=True)]
    plan = BundlePlan(bundle_id="skill_s1", product_id="P1", slots=slots)
    manifest = runner.run_bundle(plan, out_dir=tmp_path)

    assert manifest["summary"]["ok"] == 3  # 1 特写 + 2 槽位
    first = calls[0]
    assert "商品标准特写" in first["prompt"] or "标准特写" in first["prompt"]
    assert first["refs"] and any("flat_1.png" in r for r in first["refs"])
    # 后续槽位: 特写图必须是参考图第一位
    assert calls[1]["refs"][0].endswith("P1_00_商品标准特写.png")
    assert calls[2]["refs"][0].endswith("P1_00_商品标准特写.png")
    assert (tmp_path / "P1_00_商品标准特写.png").exists()
