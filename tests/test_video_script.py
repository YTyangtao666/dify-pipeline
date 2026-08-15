"""video_script 模块测试：脚本库加载、{}台词提取、分类选择、9:16生图提示词"""
import json

import pytest

from scripts.pipeline import video_script

SAMPLE = [
    {"编号": "1", "分类": "真人博主真实种草", "视频选题": "办公桌常驻杯",
     "主要目的": "真实种草",
     "视频脚本": "时长：15秒。0-3秒：拍法：近景。声音：{我的工位全靠它}。3-6秒：声音：{小猫杯很治愈}。\n6-11秒：声音：{随手喝一口}。11-15秒：声音：{推荐看看}。",
     "生图参考提示词": "年轻女性生活方式博主在办公场景使用奶白色保温杯，9:16竖屏。",
     "分镜图": "[附件:分镜图-1.png]"},
    {"编号": "11", "分类": "痛点解决型广告", "视频选题": "普通杯子太单调",
     "主要目的": "解决审美痛点",
     "视频脚本": "时长：15秒。0-5秒：声音：{普通杯子太丑了}。5-15秒：声音：{换它之后幸福感爆棚}。",
     "生图参考提示词": "极简风格产品主视觉，奶白保温杯，9:16竖屏。",
     "分镜图": "[附件:分镜图-11.png]"},
]


@pytest.fixture
def lib_file(tmp_path):
    f = tmp_path / "video_scripts.json"
    f.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    return f


class TestLoad:
    def test_load_library(self, lib_file):
        lib = video_script.ScriptLibrary(lib_file)
        assert lib.size == 2
        cats = lib.categories()
        assert "真人博主真实种草" in cats

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            video_script.ScriptLibrary(tmp_path / "nope.json")


class TestPick:
    def test_pick_by_category_deterministic(self, lib_file):
        lib = video_script.ScriptLibrary(lib_file)
        s1 = lib.pick("真人博主真实种草", seed=42)
        s2 = lib.pick("真人博主真实种草", seed=42)
        assert s1["编号"] == s2["编号"]      # 同 seed 稳定
        assert s1["分类"] == "真人博主真实种草"

    def test_pick_unknown_category_falls_back(self, lib_file):
        lib = video_script.ScriptLibrary(lib_file)
        s = lib.pick("不存在的分类", seed=1)
        assert s["编号"] in {"1", "11"}


class TestParse:
    def test_extract_voiceover_from_braces(self, lib_file):
        """从脚本提取 {台词} 作为口播文案"""
        lib = video_script.ScriptLibrary(lib_file)
        s = lib.pick("真人博主真实种草", seed=42)
        vo = video_script.extract_voiceover(s["视频脚本"])
        assert "我的工位全靠它" in vo
        assert "{" not in vo and "}" not in vo

    def test_extract_shots_with_timecodes(self, lib_file):
        """解析分镜：按 秒段 切分，每段含拍法/画面/声音要素"""
        lib = video_script.ScriptLibrary(lib_file)
        s = lib.pick("真人博主真实种草", seed=42)
        shots = video_script.parse_shots(s["视频脚本"])
        assert len(shots) >= 4
        assert shots[0]["time"] == "0-3秒"
        assert any("拍法" in sh["text"] or "声音" in sh["text"] for sh in shots)

    def test_no_braces_returns_whole(self):
        vo = video_script.extract_voiceover("一段没有台词标记的脚本")
        assert "没有台词标记" in vo

    def test_estimate_duration(self):
        assert video_script.estimate_duration("0-3秒：A。3-6秒：B。6-11秒：C。11-15秒：D。") == 15.0


class TestBuild:
    def test_build_video_plan(self, lib_file):
        """视频计划：脚本 + 口播 + 时长 + 生图提示词"""
        lib = video_script.ScriptLibrary(lib_file)
        s = lib.pick("痛点解决型广告", seed=7)
        plan = video_script.build_video_plan(s, product_title="保温杯")
        assert plan["script_id"] == "11"
        assert plan["tts_text"]          # 非空口播
        assert plan["duration_est"] > 0
        assert "9:16" in plan["image_prompt"] or "竖屏" in plan["image_prompt"]
