#!/usr/bin/env python3
"""分镜 -> 每镜头音轨(mp3): 旁白+台词按角色分声。

角色声库(edge-tts 神经音色,ALL_PROXY 走代理):
- 旁白 narrator: zh-CN-YunyangNeural (低沉播音) rate -12% pitch -2Hz
- 林渊(少年主角): zh-CN-YunxiNeural rate -8%
- 赵管事(反派): zh-CN-YunjianNeural rate +5%
- 系统(机械冰冷): zh-CN-YunjianNeural rate -15% pitch -4Hz
台词识别: dialogue[].role 字段;旁白 narration。
输出 audio/shot_XX.mp3 (每镜头一个文件,旁白+台词顺序拼接)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "comic"
AUDIO = OUT_DIR / "audio"
FFMPEG = "ffmpeg"

VOICE_MAP = {
    # 旁白:沉稳播音腔压低
    "narrator": ("zh-CN-YunyangNeural", "-12%", "-2Hz"),
    # 秦阳:18岁少年主角,清亮少年音
    "秦阳": ("zh-CN-YunxiNeural", "-8%", "-1Hz"),
    # 壮汉(逃犯):粗犷凶狠
    "壮汉": ("zh-CN-YunjianNeural", "+5%", "+2Hz"),
    "逃犯": ("zh-CN-YunjianNeural", "+5%", "+2Hz"),
    # 蓝若:18岁冷艳校花
    "蓝若": ("zh-CN-XiaoyiNeural", "-10%", "-1Hz"),
    # 秦岚:审判庭冷酷女长官(青年偏高冷)
    "秦岚": ("zh-CN-XiaoyiNeural", "+0%", "-4Hz"),
    # 蓝莹:30岁女管家
    "蓝莹": ("zh-CN-XiaoxiaoNeural", "-15%", "-3Hz"),
    # 黑衣人:统一低沉机械
    "黑衣男": ("zh-CN-YunjianNeural", "-15%", "-5Hz"),
    "另一黑衣男": ("zh-CN-YunjianNeural", "-15%", "-5Hz"),
    # 兜底:未登记角色一律旁白声
    "_default": ("zh-CN-YunyangNeural", "-12%", "-2Hz"),
}

CLEAN_RE = re.compile(r'^["\'\u201c\u201d]+|["\'\u201c\u201d]+$')


def clean(line: str) -> str:
    return CLEAN_RE.sub("", line.strip())


async def synth_one(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    """edge-tts 概率性 NoAudioReceived(服务端抖动),重试3次。"""
    import edge_tts.exceptions

    for attempt in range(3):
        c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        try:
            await c.save(str(out))
        except edge_tts.exceptions.NoAudioReceived:
            print(f"    tts retry {attempt+1}/3: {text[:20]}...")
            await asyncio.sleep(2)
            continue
        if out.stat().st_size == 0:
            print(f"    tts empty retry {attempt+1}/3: {text[:20]}...")
            await asyncio.sleep(2)
            continue
        return
    raise RuntimeError(f"tts failed after 3 retries: {text[:40]}")


def concat(files: list[Path], out: Path, gap_ms: int = 250) -> None:
    """ffmpeg 拼接,镜头内旁白与台词间留 0.25s 气口。"""
    if len(files) == 1:
        out.write_bytes(files[0].read_bytes())
        return
    lst = AUDIO / f"_{out.stem}_list.txt"
    lst.write_text("\n".join(f"file '{f.name}'" for f in files), encoding="utf-8")
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)],
                   check=True, capture_output=True)


async def main() -> None:
    os.environ.setdefault("ALL_PROXY", "http://127.0.0.1:7897")
    AUDIO.mkdir(parents=True, exist_ok=True)
    shots = json.loads((OUT_DIR / "storyboard.json").read_text(encoding="utf-8"))

    for s in shots:
        no = int(s.get("shot") or 0)
        final = AUDIO / f"shot_{no:02d}.mp3"
        if final.exists() and final.stat().st_size > 0:
            print(f"[{no}] exists")
            continue
        parts = []
        nar = clean(s.get("narration") or "")
        if nar:
            f = AUDIO / f"shot_{no:02d}_nar.mp3"
            v, r, p = VOICE_MAP["narrator"]
            await synth_one(nar, v, r, p, f)
            parts.append(f)
        for d in s.get("dialogue") or []:
            role = d.get("role") or "narrator"
            line = clean(d.get("line") or "")
            if not line:
                continue
            f = AUDIO / f"shot_{no:02d}_dlg_{role}.mp3"
            v, r, p = VOICE_MAP.get(role) or VOICE_MAP["_default"]
            await synth_one(line, v, r, p, f)
            parts.append(f)
        if not parts:
            # 无旁白无台词:静音 2s 占位
            subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=24000:cl=mono", "-t", "2",
                            "-c:a", "libmp3lame", str(final)],
                           check=True, capture_output=True)
            print(f"[{no}] silent 2s")
            continue
        real_parts = [p for p in parts if p.exists() and p.stat().st_size > 0]
        concat(real_parts, final)
        # 清理分片
        for p in parts:
            p.unlink(missing_ok=True)
        print(f"[{no}] audio done ({len(real_parts)} parts)")

    print("tts complete ->", AUDIO)


if __name__ == "__main__":
    asyncio.run(main())
