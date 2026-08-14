"""04 视频合成：edge-tts 口播 + FFmpeg 图片轮播 → mp4。"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


async def tts_to_mp3(text: str, voice: str, out_path: Path) -> float:
    """edge-tts 合成口播，返回音频时长（秒）。"""
    import edge_tts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))
    return probe_duration(out_path)


def probe_duration(audio: Path) -> float:
    """ffprobe 读取媒体时长。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr[:200]}")
    return float(r.stdout.strip())


def build_ffmpeg_cmd(images: list[Path], audio: Path, out_path: Path,
                     per_image_sec: float = 4.0) -> list[str]:
    """构建 ffmpeg 命令：图片轮播 + 音轨，时长以音频为准。"""
    n = len(images)
    assert n >= 1, "至少需要一张图片"
    cmd: list[str] = ["ffmpeg", "-y"]
    # 每张图作为一路输入，loop 播放
    for img in images:
        cmd += ["-loop", "1", "-t", f"{per_image_sec:.2f}", "-i", str(img)]
    cmd += ["-i", str(audio)]
    # 拼接图片流
    inputs = "".join(f"[{i}:v]scale=1080:1080:force_original_aspect_ratio=decrease,"
                     f"pad=1080:1080:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1[v{i}];"
                     for i in range(n))
    streams = "".join(f"[v{i}]" for i in range(n))
    filter_complex = (
        f"{inputs}{streams}concat=n={n}:v=1:a=0[vout]"
    )
    total = per_image_sec * n
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", f"{n}:a",
        "-t", f"{total:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out_path),
    ]
    return cmd


async def compose_video(images: list[Path], tts_text: str, voice: str,
                        out_path: Path, per_image_sec: float = 4.0) -> Path:
    """完整合成：TTS → ffmpeg。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path = out_path.with_suffix(".mp3")
    await tts_to_mp3(tts_text, voice, audio_path)
    probe_duration(audio_path)

    cmd = build_ffmpeg_cmd(images, audio_path, out_path, per_image_sec)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 合成失败: {r.stderr[-500:]}")
    return out_path
