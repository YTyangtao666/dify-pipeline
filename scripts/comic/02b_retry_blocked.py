#!/usr/bin/env python3
"""对内容安全拦截的镜头(shot 10/11)做安全改写并重试生成。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.pipeline.config import Config
from scripts.pipeline.imagegen import generate_image

OUT_DIR = ROOT / "output" / "comic"
PANELS = OUT_DIR / "panels"

STYLE_SUFFIX = (
    "。中国风暗黑玄幻漫画风格,厚重水墨质感,冷色调,电影级光影,"
    "竖屏构图,画面中禁止出现任何文字、水印、对话框"
)

# 安全改写:去掉「濒死/血沫/瞳孔涣散/生命气息微弱」等自残濒死信号,保留氛围
SAFE_REWRITE = {
    4: None,  # 纯 delivery 抖动,原prompt重试即可
    10: (
        "全景。赵管事（中年，面容尖刻，头戴黑色管事帽，身穿深蓝色管事长袍，体型微胖）"
        "转身离去的背影，袍角被夜风掀起，靴底踩在青石板上。远景处林渊（18岁，黑发凌乱，"
        "面容清瘦，身穿破旧杂役灰布短打，体型单薄）仍倒在泥塘边，身影渺小。深秋雨夜，"
        "细密雨丝落下，环境阴冷昏暗，青玄宗杂役院的灯火在远处明明灭灭。"
    ),
    11: (
        "特写。林渊（18岁，黑发凌乱沾满泥污，面容清瘦，身穿破旧杂役灰布短打，体型单薄）"
        "伏在泥水中的侧脸，雨水顺着他紧闭的眼睫滑落，眉头紧锁，神情疲惫却带着隐忍。"
        "湿发贴在脸颊。背景是夜色中的泥塘与雨丝，画面昏暗冷寂，只有远处一盏灯笼的微光。"
    ),
}


async def main() -> None:
    cfg = Config.from_env()
    for no, desc in SAFE_REWRITE.items():
        out = PANELS / f"shot_{no:02d}.png"
        if out.exists():
            print(f"[{no}] exists")
            continue
        shots = {int(s["shot"]): s for s in json.loads(
            (OUT_DIR / "storyboard.json").read_text(encoding="utf-8"))}
        prompt = (desc or shots[no]["panel_desc"]) + STYLE_SUFFIX
        for attempt in range(3):
            print(f"[{no}] attempt {attempt + 1} ...")
            try:
                await generate_image(
                    cfg, prompt, out, size="9:16",
                    reference_images=[PANELS / "shot_01.png"],
                )
                print(f"[{no}] done")
                break
            except Exception as e:  # noqa: BLE001
                print(f"[{no}] FAILED: {str(e)[:120]}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
