#!/usr/bin/env python3
"""合成最终竖屏视频: 分镜图 + Ken Burns 运镜 + 每镜头音轨对齐 + 底部字幕。

流程:
1. 每镜头: zoompan 做 Ken Burns (时长远=该镜头音轨时长+0.6s 余量)
   - zoom_in / zoom_out / pan_left / pan_right / pan_up / pan_down / none(微推)
2. 音轨: audio/shot_XX.mp3;不足补静音
3. 字幕: narration/dialogue 逐镜头一条 drawtext(大号白字+黑描边,底部)
4. concat 全部镜头 + 音轨 -> comic_ep1.mp4 (1080x1920)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "comic"
PANELS = OUT_DIR / "panels"
AUDIO = OUT_DIR / "audio"
TMP = OUT_DIR / "tmp_clips"
FINAL = OUT_DIR / "comic_ep1.mp4"
FFMPEG = "ffmpeg"
W, H = 1080, 1920
FPS = 30

CLEAN_RE = re.compile(r'^["\'“”]+|["\'“”]+$')


def audio_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 2.0


def zoompan_expr(motion: str, dur_frames: int) -> str:
    """生成 zoompan 表达式: 基于总帧数的线性进度。"""
    n = max(dur_frames, 1)
    # 基础: 缓慢 zoom 1.0->1.12
    if motion == "zoom_in":
        return f"zoom='1+0.0018*on/({n}/{n})*{n}*0.0018*100/100+0.00014*on':d={n}"
    # 简化方案: 用固定速率
    return ""


def build_filter(motion: str, frames: int) -> str:
    """返回完整 filter chain: scale + zoompan + 格式化。"""
    if motion == "zoom_in":
        z = f"min(1+0.14*on/{frames},1.15)"
        x = "(iw-iw/zoom)/2"; y = "(ih-ih/zoom)/2"
    elif motion == "zoom_out":
        z = f"max(1.15-0.14*on/{frames},1.0)"
        x = "(iw-iw/zoom)/2"; y = "(ih-ih/zoom)/2"
    elif motion == "pan_left":
        z = "1.12"; x = f"(iw-iw/zoom)*(1-on/{frames})"; y = "(ih-ih/zoom)/2"
    elif motion == "pan_right":
        z = "1.12"; x = f"(iw-iw/zoom)*on/{frames}"; y = "(ih-ih/zoom)/2"
    elif motion == "pan_up":
        z = "1.12"; x = "(iw-iw/zoom)/2"; y = f"(ih-ih/zoom)*(1-on/{frames})"
    elif motion == "pan_down":
        z = "1.12"; x = "(iw-iw/zoom)/2"; y = f"(ih-ih/zoom)*on/{frames}"
    else:  # none -> 极缓推,避免死帧感
        z = f"min(1+0.06*on/{frames},1.06)"
        x = "(iw-iw/zoom)/2"; y = "(ih-ih/zoom)/2"
    return (
        f"scale={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
        f"format=yuv420p"
    )


def esc(t: str) -> str:
    """drawtext 转义。"""
    return (t.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\u2019").replace("%", "\\%"))


def wrap_chars(text: str, per_line: int = 16) -> str:
    lines = [text[i:i + per_line] for i in range(0, len(text), per_line)]
    return "\n".join(lines)


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    shots = json.loads((OUT_DIR / "storyboard.json").read_text(encoding="utf-8"))
    clip_list = []

    font = "/System/Library/Fonts/PingFang.ttc"
    for s in shots:
        no = int(s.get("shot") or 0)
        img = PANELS / f"shot_{no:02d}.png"
        aud = AUDIO / f"shot_{no:02d}.mp3"
        clip = TMP / f"clip_{no:02d}.mp4"
        clip_list.append(clip)
        if clip.exists():
            continue
        if not img.exists():
            print(f"[{no}] missing panel, skip")
            continue

        dur = audio_duration(aud) + 0.7 if aud.exists() else 2.5
        frames = int(dur * FPS)
        motion = s.get("motion") or "none"
        vf = build_filter(motion, frames)

        # 字幕文本: 优先台词,否则旁白
        sub = ""
        for d in s.get("dialogue") or []:
            sub += clean(d.get("line") or "") + " "
        sub = sub.strip() or CLEAN_RE.sub("", (s.get("narration") or "").strip())
        if sub:
            wrapped = wrap_chars(sub)
            vf += (
                f",drawtext=fontfile='{font}':text='{esc(wrapped)}'"
                f":fontcolor=white:fontsize=52:borderw=3:bordercolor=black"
                f":line_spacing=14:x=(w-text_w)/2:y=h-360:shadowx=2:shadowy=2:shadowcolor=black@0.6"
            )

        cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(img)]
        if aud.exists() and aud.stat().st_size > 0:
            cmd += ["-i", str(aud)]
        cmd += ["-filter_complex", vf]
        if aud.exists() and aud.stat().st_size > 0:
            cmd += ["-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-shortest"]
        else:
            cmd += ["-map", "0:v", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-t", f"{dur:.2f}"]
        cmd += ["-r", str(FPS), "-pix_fmt", "yuv420p", str(clip)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[{no}] ffmpeg err: {r.stderr[-400:]}")
            continue
        print(f"[{no}] clip ok ({dur:.1f}s {motion})")

    # concat
    lst = TMP / "list.txt"
    ok_clips = [c for c in clip_list if c.exists()]
    lst.write_text("\n".join(f"file '{c.name}'" for c in ok_clips), encoding="utf-8")
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(FINAL)], capture_output=True, text=True)
    if r.returncode != 0:
        print("concat err:", r.stderr[-400:])
        sys.exit(1)
    print(f"DONE -> {FINAL}")


def clean(t: str) -> str:
    return CLEAN_RE.sub("", t.strip())


if __name__ == "__main__":
    main()
