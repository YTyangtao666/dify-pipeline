#!/usr/bin/env python3
"""01 分镜层:adapted.json(场景剧本) -> storyboard.json(镜头序列)。

输入改为 00b 的 adapted.json(已清洗+快节奏改编),本层只做「场景→镜头」的视觉翻译:
- 每场景 2-3 镜(事件密度高的场景 3 镜),总镜头 12-20
- panel_desc 直接复用 characters[].look 做跨镜一致性锚(不再靠 LLM 记忆)
- narration/dialogue 从场景剧本分发到镜头,一字不改
输出 storyboard.json:[{shot, scene_id, panel_desc, narration, dialogue, motion, emotion}]
——02/03/04 下游 schema 不变,零改动。
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

PROMPT = """你是顶级漫画分镜师。把下面的【漫剧场景剧本】(已清洗、已按快节奏改编)切成竖屏(9:16)条漫分镜。

【角色外貌锚】(panel_desc 里人物每次出场都必须原样引用对应的 look 描述):
{characters}

【场景剧本】(JSON):
{scenes}

【任务】每个场景切 2-3 个镜头(事件多的场景切3镜),每镜头 2-6 秒画面。输出 JSON 数组,每个元素:
{{
  "shot": 镜头总序号(int,从1开始跨场景连续),
  "scene_id": 所属场景id(int),
  "panel_desc": "画面描述——用于AI生图。必须包含:出场人物外貌(从上面【角色外貌锚】原样引用对应角色完整look)、表情动作、景别(特写/中景/全景)、环境光线。中文,80-150字。风格统一为:中国风暗黑玄幻漫画,厚重水墨感,冷色调,电影级光影。禁止画面中出现任何文字。",
  "narration": "本镜头旁白(从该场景 narration 数组中取1-2句分配,原文不改,不加字)",
  "dialogue": [{{"role": "角色名", "line": "台词原文"}}],  // 从该场景 dialogues 分配到本镜头,无台词给 []
  "motion": "zoom_in|zoom_out|pan_left|pan_right|none 之一,根据画面情绪选",
  "emotion": "该镜头情绪基调,2-4字,如:压抑/愤怒/爆发/阴冷"
}}

【铁律】
1. narration 和 dialogue 必须来自上面场景剧本,一字不改,禁止原创
2. 场景的所有 narration 句和 dialogue 必须全部分配完,不许丢(结尾悬念句放该场景最后一镜)
3. panel_desc 里人物外貌描述每镜完整重复(跨镜一致性的锚,直接引用外貌锚)
4. 动作戏场景:景别要切(全景交代→中景对峙→特写爆发),运镜跟情绪走
5. 只输出 JSON 数组,不要任何其他文字/markdown代码块"""


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


def validate(data: list, adapted: dict) -> str | None:
    """校验:narration/dialogue 全量分发+镜头数。"""
    if not (10 <= len(data) <= 24):
        return f"镜头数 {len(data)} 超范围(10-24)"
    # narration 全量分发校验
    want_nar = []
    for sc in adapted["scenes"]:
        want_nar.extend(sc.get("narration") or [])
    got_nar = [s.get("narration") or "" for s in data if s.get("narration")]
    # 旁白可能两句拼一镜,做包含式校验:每句 want 必须出现在某镜头里
    missing = [n for n in want_nar if not any(n in g for g in got_nar)]
    if missing:
        return f"丢失旁白 {len(missing)} 句: {missing[:2]}"
    # dialogue 校验
    want_dlg = sum(len(sc.get("dialogues") or []) for sc in adapted["scenes"])
    got_dlg = sum(len(s.get("dialogue") or []) for s in data)
    if got_dlg < want_dlg - 1:  # 容忍1条被合并
        return f"丢失台词 {want_dlg - got_dlg} 条"
    return None


async def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "adapted.json"
    adapted = json.loads(src.read_text(encoding="utf-8"))

    chars_desc = "\n".join(
        f"- {c['name']}: {c['look']}" for c in adapted.get("characters", [])
    )
    prompt = (PROMPT
              .replace("{characters}", chars_desc)
              .replace("{scenes}", json.dumps(adapted["scenes"], ensure_ascii=False)))

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000,
        "temperature": 0.3,
        "stream": False,
    }
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"},
        proxy=PROXY, timeout=600.0,
    ) as client:
        last_err = ""
        for attempt in range(5):
            try:
                resp = await client.post("/chat/completions", json=payload)
            except httpx.HTTPError as e:
                print(f"[{attempt+1}/5] net: {str(e)[:100]}")
                await asyncio.sleep(3)
                continue
            if resp.status_code != 200:
                print(f"[{attempt+1}/5] HTTP {resp.status_code}: {resp.text[:120]}")
                await asyncio.sleep(5)
                continue
            body = resp.json()
            content = body["choices"][0]["message"]["content"] or ""
            data = extract_json_array(content)
            if data:
                err = validate(data, adapted)
                if err:
                    last_err = err
                    print(f"[{attempt+1}/5] 分发校验不过: {err},重试")
                    await asyncio.sleep(2)
                    continue
                out = OUT_DIR / "storyboard.json"
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                print(f"OK {len(data)} shots -> {out}")
                for s in data[:4]:
                    print(f"  shot{s.get('shot')}(S{s.get('scene_id')}): "
                          f"{s.get('panel_desc', '')[:60]}...")
                return
            print(f"[{attempt+1}/5] unparsable, content[:200]: {content[:200]}")
            await asyncio.sleep(2)
    sys.exit(f"storyboard generation failed: {last_err}")


if __name__ == "__main__":
    asyncio.run(main())
