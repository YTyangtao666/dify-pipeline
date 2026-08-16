"""L5 框架库测试：加载/迁入8屏框架/按条件筛选/score更新（L11回流接口）"""
import json

import pytest

from scripts.pipeline.analyzer import framework as fw


@pytest.fixture
def lib_file(tmp_path):
    # 注意：空 frameworks 文件会触发自动播种 8 屏框架（生产语义）。
    # 本夹具放一个占位框架避免播种，专测通用 CRUD；播种语义由下方独立测试覆盖。
    f = tmp_path / "frameworks.json"
    f.write_text(json.dumps({"frameworks": [
        {"id": "fw_seed", "type": "详情页", "name": "seed", "structure": [],
         "applies_to": {}, "score": {"wins": 0, "losses": 0, "win_rate": 0.0}}
    ]}, ensure_ascii=False), encoding="utf-8")
    return f


class TestLibrary:
    def test_load_existing_ok(self, lib_file):
        lib = fw.FrameworkLibrary(lib_file)
        assert lib.size == 1
        assert lib.get("fw_seed") is not None

    def test_missing_file_creates_default_with_8screen(self, tmp_path):
        """缺省时自动迁入 8 屏视觉逼单框架（fw_8screen_v1）"""
        lib = fw.FrameworkLibrary(tmp_path / "new.json")
        assert lib.size == 1
        f = lib.get("fw_8screen_v1")
        assert f is not None
        assert len(f["structure"]) == 8
        assert f["score"]["win_rate"] == 0.0

    def test_migrate_8screen_preserves_structure(self, lib_file):
        from scripts.pipeline import storyboard
        lib = fw.FrameworkLibrary(lib_file)
        lib.migrate_8screen()
        f = lib.get("fw_8screen_v1")
        assert f["structure"][0]["name"] == storyboard.EIGHT_SCREENS[0]["name"]
        assert f["source"] == "飞书方法论文档"
        # 幂等：seed + 8屏 = 2
        lib.migrate_8screen()
        assert lib.size == 2


class TestSelect:
    def test_select_by_scenario(self, tmp_path):
        lib = fw.FrameworkLibrary(tmp_path / "x.json")
        lib.add({"id": "fw_a", "type": "主图", "name": "A",
                 "structure": [], "applies_to": {"客单": "高客单"},
                 "score": {"wins": 0, "losses": 0}})
        picked = lib.select(framework_type="主图", scenario={"客单": "高客单"})
        assert picked and picked[0]["id"] == "fw_a"

    def test_select_ranks_by_win_rate(self, tmp_path):
        lib = fw.FrameworkLibrary(tmp_path / "x.json")
        lib.add({"id": "fw_low", "type": "主图", "name": "L", "structure": [],
                 "applies_to": {}, "score": {"wins": 2, "losses": 8, "win_rate": 0.2}})
        lib.add({"id": "fw_high", "type": "主图", "name": "H", "structure": [],
                 "applies_to": {}, "score": {"wins": 8, "losses": 2, "win_rate": 0.8}})
        picked = lib.select(framework_type="主图")
        assert picked[0]["id"] == "fw_high"


class TestScoreUpdate:
    def test_update_score_recomputes_win_rate(self, tmp_path):
        """红线2：score 只经 update_score 修改（L11 专用接口）"""
        lib = fw.FrameworkLibrary(tmp_path / "x.json")
        lib.add({"id": "fw_x", "type": "主图", "name": "X", "structure": [],
                 "applies_to": {}, "score": {"wins": 0, "losses": 0, "win_rate": 0.0}})
        lib.update_score("fw_x", win=True)
        lib.update_score("fw_x", win=True)
        lib.update_score("fw_x", win=False)
        f = lib.get("fw_x")
        assert f["score"]["wins"] == 2 and f["score"]["losses"] == 1
        assert abs(f["score"]["win_rate"] - 2 / 3) < 1e-3  # round(4) 精度

    def test_update_unknown_id_raises(self, tmp_path):
        lib = fw.FrameworkLibrary(tmp_path / "x.json")
        with pytest.raises(KeyError):
            lib.update_score("nope", win=True)

    def test_retire_low_win_rate(self, tmp_path):
        """胜率过低且样本足够的框架被淘汰（archived）"""
        lib = fw.FrameworkLibrary(tmp_path / "x.json")
        lib.add({"id": "fw_bad", "type": "主图", "name": "B", "structure": [],
                 "applies_to": {}, "score": {"wins": 1, "losses": 9, "win_rate": 0.1}})
        lib.retire_if_stale(min_samples=10)
        assert lib.get("fw_bad").get("archived") is True
        # select 默认排除 archived
        assert lib.select(framework_type="主图") == []
