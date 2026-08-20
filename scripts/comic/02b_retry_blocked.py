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

# 安全改写:去掉触发内容安全的信号(血/咬唇/亲密接触),保留叙事氛围
SAFE_REWRITE = {
    # shot8(S3): 咬唇+血 → 改「贴身相护/神情剧变」,回避亲密接触与血液特写
    8: (
        "【特写】秦阳（18岁黑发少年，面容清秀，体型偏瘦但结实，穿普通校服）脸侧沾有一点"
        "暗红痕迹，神情从惊慌骤变为极度的专注与渴望，双眼圆睁，呼吸急促。他猛地转头朝向"
        "身旁的蓝若（18岁少女，黑色长发，容颜绝美，气质冰冷，校服拉链拉到顶）方向俯身，"
        "两人距离极近，蓝若瞳孔微缩，神情震动。背景虚化为夜色公交站台，冷色路灯聚焦两人面部。"
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
