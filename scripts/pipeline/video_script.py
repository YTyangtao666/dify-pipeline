"""100 条带货视频脚本库驱动：分类选模板、{台词}提取口播、分镜解析、9:16 生图提示词。

数据来源：data/video_scripts_100.json（飞书多维表格导出）。
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path


class ScriptLibrary:
    """脚本库：按分类选择模板（同 seed 确定性选择，便于复现）。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"脚本库不存在: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._scripts = [s for s in data if s.get("视频脚本")]

    @property
    def size(self) -> int:
        return len(self._scripts)

    def categories(self) -> list[str]:
        return sorted({s.get("分类", "") for s in self._scripts if s.get("分类")})

    def pick(self, category: str, seed: int = 0) -> dict:
        pool = [s for s in self._scripts if s.get("分类") == category]
        if not pool:
            pool = self._scripts
        rng = random.Random(seed)
        return rng.choice(pool)


def extract_voiceover(script_text: str) -> str:
    """提取 {台词} 里的口播文案；无标记时返回原文。"""
    braces = re.findall(r"[{｛]([^{}｛｝]+)[}｝]", script_text or "")
    if braces:
        return " ".join(b.strip() for b in braces if b.strip())
    return (script_text or "").strip()


def parse_shots(script_text: str) -> list[dict]:
    """按秒段（如 0-3秒：）切分镜。"""
    text = script_text or ""
    # 按秒段标记切
    marks = list(re.finditer(r"(\d+(?:\.\d+)?-\d+(?:\.\d+)?秒)[：:]", text))
    if not marks:
        return [{"time": "", "text": text.strip()}] if text.strip() else []
    shots = []
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[start:end].strip()
        tm = re.match(r"(\d+(?:\.\d+)?-\d+(?:\.\d+)?秒)", seg)
        shots.append({"time": tm.group(1) if tm else "", "text": seg})
    return shots


def estimate_duration(script_text: str) -> float:
    """从秒段标记估算总时长（取最大结束秒）。"""
    ends = [float(m) for m in re.findall(r"\d+(?:\.\d+)?-(\d+(?:\.\d+)?)秒", script_text or "")]
    if not ends:
        # 兜底：按中文语速 4.5 字/秒
        return round(len(script_text or "") / 4.5, 1)
    return max(ends)


def build_video_plan(script: dict, product_title: str = "") -> dict:
    """把一条脚本模板转成视频生产计划。"""
    st = script.get("视频脚本", "")
    vo = extract_voiceover(st)
    if product_title:
        vo = f"{product_title}。{vo}"
    return {
        "script_id": str(script.get("编号", "")),
        "category": script.get("分类", ""),
        "topic": script.get("视频选题", ""),
        "purpose": script.get("主要目的", ""),
        "tts_text": vo,
        "duration_est": estimate_duration(st),
        "shots": parse_shots(st),
        "image_prompt": script.get("生图参考提示词", ""),
    }


DEFAULT_LIBRARY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "video_scripts_100.json"


def default_library() -> ScriptLibrary:
    return ScriptLibrary(DEFAULT_LIBRARY_PATH)
