#!/usr/bin/env python3
"""合成最终竖屏视频 v2: zoompan 运镜 + PIL 字幕条 PNG overlay(绕开 ffmpeg 无 drawtext)。

每镜头:
1. PIL 渲染字幕条(1080x320 半透明黑底圆角+白字 PingFang) -> tmp_clips/sub_XX.png
2. ffmpeg: 图 + zoompan + overlay 字幕 + 音轨 -> clip_XX.mp4 (时=音轨+0.7s)
3. concat -> comic_ep1.mp4
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "comic"
PANELS = OUT_DIR / "panels"
AUDIO = OUT_DIR / "audio"
TMP = OUT_DIR / "tmp_clips"
FINAL = OUT_DIR / "comic_ep1.mp4"
FFMPEG = "ffmpeg"
W, H = 1080, 1920
FPS = 30
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

CLEAN_RE = re.compile(r'^["\'“”]+|["\'“”]+$')


def clean(t: str) -> str:
    return CLEAN_RE.sub("", t.strip())


def audio_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 2.0


def build_filter(motion: str, frames: int) -> str:
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
    else:
        z = f"min(1+0.06*on/{frames},1.06)"
        x = "(iw-iw/zoom)/2"; y = "(ih-ih/zoom)/2"
    return (
        f"[0:v]scale={W * 2}:{H * 2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}[base]"
    )


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""
            continue
        t = cur + ch
        if font.getbbox(t)[2] > max_w:
            lines.append(cur); cur = ch
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines[:3]  # 最多3行


def make_subtitle_png(text: str, out: Path) -> None:
    """半透明黑底圆角条 + 白字 + 阴影,固定底部。"""
    bar_w, pad = 980, 28
    font = ImageFont.truetype(FONT, 46)
    lines = wrap_text(text, font, bar_w - pad * 2)
    line_h = 64
    bar_h = line_h * len(lines) + pad * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0 = (W - bar_w) // 2
    y0 = H - 210 - bar_h
    d.rounded_rectangle(
        [x0, y0, x0 + bar_w, y0 + bar_h], radius=22,
        fill=(8, 8, 12, 178),
    )
    y = y0 + pad
    for ln in lines:
        w = font.getbbox(ln)[2]
        x = (W - w) // 2
        d.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 200))
        d.text((x, y), ln, font=font, fill=(245, 242, 235, 255))
        y += line_h
    img.save(out)


def main() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    shots = json.loads((OUT_DIR / "storyboard.json").read_text(encoding="utf-8"))
    clip_list = []

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
        vf = build_filter(s.get("motion") or "none", frames)

        sub = ""
        for d in s.get("dialogue") or []:
            sub += clean(d.get("line") or "") + " "
        sub = sub.strip() or clean(s.get("narration") or "")

        inputs = ["-loop", "1", "-i", str(img)]
        if sub:
            subpng = TMP / f"sub_{no:02d}.png"
            make_subtitle_png(sub, subpng)
            inputs += ["-i", str(subpng)]
            vf += f";[base][1:v]overlay=(W-w)/2:0[vout]"
        if aud.exists() and aud.stat().st_size > 0:
            inputs += ["-i", str(aud)]

        cmd = [FFMPEG, "-y"] + inputs + ["-filter_complex", vf]
        maps = ["-map", "[vout]" if sub else "[base]"]
        if aud.exists() and aud.stat().st_size > 0:
            ai = 2 if sub else 1
            maps += ["-map", f"{ai}:a"]
            cmd += maps + ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                           "-c:a", "aac", "-b:a", "160k", "-shortest",
                           "-t", f"{dur:.2f}"]
        else:
            cmd += maps + ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                           "-t", f"{dur:.2f}"]
        cmd += ["-r", str(FPS), "-pix_fmt", "yuv420p", str(clip)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[{no}] ffmpeg err: {r.stderr[-300:]}")
            continue
        print(f"[{no}] clip ok ({dur:.1f}s {s.get('motion')})")

    ok_clips = [c for c in clip_list if c.exists()]
    lst = TMP / "list.txt"
    lst.write_text("\n".join(f"file '{c.name}'" for c in ok_clips), encoding="utf-8")
    r = subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(FINAL)], capture_output=True, text=True)
    if r.returncode != 0:
        print("concat err:", r.stderr[-300:])
        sys.exit(1)
    print(f"DONE -> {FINAL}")


if __name__ == "__main__":
    main()
