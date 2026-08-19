#!/usr/bin/env python3
"""小说→分镜脚本:LLM 把章节正文切成镜头序列(画面+台词/旁白+运镜+情绪)。

输出 storyboard.json:[{shot, panel_desc, narration, dialogue, motion, emotion, voice_role}]
- panel_desc: 生图 prompt 素材(中文画面描述,含人物外观锚)
- narration: 旁白(第三人称叙述)
- dialogue: 台词 [{role, line}]
- motion: Ken Burns 运镜 (zoom_in/zoom_out/pan_left/pan_right/none)
- voice_role: 旁白音色/台词音色分配
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_URL = os.environ.get("ARK_BASE_URL", "")
API_KEY = os.environ.get("ARK_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v3.2")
PROXY = os.environ.get("ARK_PROXY") or None

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "comic"

PROMPT = """你是顶级漫画分镜师。把下面的小说正文改编成竖屏(9:16)条漫分镜脚本。

【任务】切成 12-16 个镜头,每镜头 2-8 秒画面。输出 JSON 数组,每个元素:
{{
  "shot": 镜头序号(int,从1开始),
  "panel_desc": "画面描述——用于AI生图。必须包含:出场人物外观(每次出现都完整重复外貌特征:年龄/发型发色/服装/体型,保证跨镜一致)、表情动作、景别(特写/中景/全景)、环境光线。中文,80-150字。风格统一为:中国风暗黑玄幻漫画,厚重水墨感,冷色调,电影级光影。禁止画面中出现任何文字。",
  "narration": "旁白,直接从原文摘选或轻度压缩,每镜头1-3句。没有旁白就空字符串。禁止原创剧情。",
  "dialogue": [{{"role": "角色名", "line": "台词原文"}}],  // 无台词给 []
  "motion": "zoom_in|zoom_out|pan_left|pan_right|none 之一,根据画面情绪选",
  "emotion": "该镜头情绪基调,2-4字,如:压抑/愤怒/爆发/阴冷"
}}

【铁律】
1. 台词和旁白必须来自原文,一字不改(台词=引号内内容,旁白=叙述句),禁止自己编
2. panel_desc 里人物外貌描述每镜完整重复(这是跨镜一致性的锚)
3. 台词比旁白优先保留——观众更爱听人说话
4. 只输出 JSON 数组,不要任何其他文字/markdown代码块

小说正文:
{chapter}"""


def extract_json_array(text: str) -> list | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "ch1_clean.txt"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    chapter = src.read_text(encoding="utf-8").strip()
    prompt = PROMPT.replace("{chapter}", chapter).replace("12-16", f"12-{limit}")

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000,
        "temperature": 0.3,
        "stream": False,
    }
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"},
        proxy=PROXY, timeout=300.0,
    ) as client:
        for attempt in range(3):
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code != 200:
                print(f"[{attempt+1}/3] HTTP {resp.status_code}: {resp.text[:150]}")
                await asyncio.sleep(3)
                continue
            body = resp.json()
            content = body["choices"][0]["message"]["content"] or ""
            data = extract_json_array(content)
            if data:
                out = OUT_DIR / "storyboard.json"
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"OK {len(data)} shots -> {out}")
                for s in data[:3]:
                    print(f"  shot{s.get('shot')}: {s.get('panel_desc','')[:60]}...")
                return
            print(f"[{attempt+1}/3] unparsable, content[:200]: {content[:200]}")
    sys.exit("storyboard generation failed")


if __name__ == "__main__":
    asyncio.run(main())
