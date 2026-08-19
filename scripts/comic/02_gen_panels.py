#!/usr/bin/env python3
"""分镜批量生图:storyboard.json -> panels/shot_XX.png (9:16, gpt-image-2)。

角色锚定策略(同 dify-pipeline 双锚定方法论):
- 先生成 shot1 作为首帧锚(主角外貌+风格定调)
- 后续镜头以 shot1 为参考图 img2img,保人物+画风一致
- --sample N 只跑前 N 镜(试制模式)
"""
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


async def main() -> None:
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0=全量
    cfg = Config.from_env()
    PANELS.mkdir(parents=True, exist_ok=True)

    shots = json.loads((OUT_DIR / "storyboard.json").read_text(encoding="utf-8"))
    if sample:
        shots = shots[:sample]

    # 首帧锚
    anchor = PANELS / "shot_01.png"
    if not anchor.exists():
        print("[1] generating anchor shot_01 ...")
        await generate_image(cfg, shots[0]["panel_desc"] + STYLE_SUFFIX, anchor,
                             size="9:16")
        print(f"[1] anchor done -> {anchor}")

    # 其余镜头 img2img
    for s in shots[1:]:
        no = int(s.get("shot") or 0)
        out = PANELS / f"shot_{no:02d}.png"
        if out.exists():
            print(f"[{no}] exists, skip")
            continue
        print(f"[{no}] generating ...")
        try:
            await generate_image(
                cfg, s["panel_desc"] + STYLE_SUFFIX, out,
                size="9:16",
                reference_images=[anchor],
            )
            print(f"[{no}] done")
        except Exception as e:  # noqa: BLE001
            print(f"[{no}] FAILED: {e}")
    print("panel generation pass complete")


if __name__ == "__main__":
    asyncio.run(main())
