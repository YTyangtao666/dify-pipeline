#!/usr/bin/env python3
"""00b LLM 改编层:清洗后正文 -> 漫剧节奏的大白话剧本(adapted.json)。

解决「剧情太慢」:
- 删:设定说明文、内心碎碎念、群聊刷屏(留关键3条)
- 压:环境描写≤1句、插叙回忆压半句
- 改:旁白全改大白话(≤15字/句);台词保留原味不动(本身已口语)
- 硬节奏:第一句必是钩子,前3场景必完成钩子→危机,场景密度=爽点间隔≤2场景
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

PROMPT = """你是爆款短剧编剧,把小说改造成【快节奏漫剧剧本】。观众是刷短视频的用户,3秒不爽就划走。

【清洗铁律】
1. 删掉:世界观设定讲解(境界体系等说明文)、超过2句的内心独白、回忆插叙、群聊刷屏(最多留3条关键消息)
2. 环境描写只留最有画面感的1句;动作戏保留动词链,砍掉形容词
3. 旁白全部改成大白话短句,每句≤15字,像短视频解说:直接、带钩子
4. 台词【原文照抄不改】,台词本身已经足够口语化
5. 每个场景必须有事件推进,纯氛围段落合并或删除

【节奏硬约束】
- 第1场景第1条旁白必须是钩子(悬念/危机/反常),禁止从背景介绍开始
- 前3个场景内必须出现第一次危机或冲突升级
- 爽点(反转/爆发/打脸)间隔最多2个场景,连续铺垫场景必须合并
- 每场景时长压到15-30秒信息量:events 3-6条、narration 1-4句、台词最多6句
- 场景总数控制在5-8个

【输出 JSON】
{{
  "scenes": [
    {{
      "scene_id": 1,
      "title": "场景名(4-8字)",
      "hook": "该场景抓人的点,一句话",
      "events": ["大白话事件链,每条≤20字,按发生顺序", ...],
      "narration": ["该场景旁白,大白话短句,≤15字/句,总共1-4句", ...],
      "dialogues": [{{"role": "角色名", "line": "台词原文"}}],
      "mood": "情绪基调2-4字"
    }}
  ],
  "characters": [
    {{"name": "角色名", "look": "外貌白描:年龄/发型发色/服装/体型/气质,50字内,每镜复用作一致性锚", "gender": "男|女", "voice_type": "少年|青年|壮汉|女青年|中年女|冷艳女"}}
  ]
}}
只输出 JSON,不要其他文字。

小说原文:
{chapter}"""


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def validate(data: dict) -> str | None:
    """轻校验:结构完整+节奏红线。返回错误信息或 None。"""
    scenes = data.get("scenes") or []
    if len(scenes) < 4:
        return f"场景太少({len(scenes)}<4),节奏会拖"
    for sc in scenes:
        if not sc.get("narration"):
            return f"S{sc.get('scene_id')} 无旁白"
        n = sc.get("narration", "")
        if isinstance(n, list) and len(n) > 4:
            return f"S{sc.get('scene_id')} 旁白超4句({len(n)})"
    for sc in scenes[:1]:
        first = (sc.get("narration") or [""])[0]
        if len(first) > 18:
            return f"第1场景首句旁白太长({len(first)}字>18),钩子必须短促"
    return None


async def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "vampire_clean.txt"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_DIR / "adapted.json"
    chapter = src.read_text(encoding="utf-8").strip()

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": PROMPT.replace("{chapter}", chapter)}],
        "max_tokens": 8000,
        "temperature": 0.3,
        "stream": False,
    }
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"},
        proxy=PROXY, timeout=300.0,
    ) as client:
        for attempt in range(3):
            try:
                resp = await client.post("/chat/completions", json=payload)
            except httpx.HTTPError as e:
                print(f"[{attempt+1}/3] net: {str(e)[:100]}")
                await asyncio.sleep(3)
                continue
            if resp.status_code != 200:
                print(f"[{attempt+1}/3] HTTP {resp.status_code}")
                await asyncio.sleep(3)
                continue
            content = resp.json()["choices"][0]["message"]["content"] or ""
            data = extract_json(content)
            if data and data.get("scenes"):
                err = validate(data)
                if err:
                    print(f"[{attempt+1}/3] 节奏校验不过: {err},重试")
                    continue
                dst.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                print(f"OK {len(data['scenes'])} scenes, "
                      f"{len(data.get('characters', []))} chars -> {dst}")
                for sc in data["scenes"]:
                    print(f"  S{sc['scene_id']} {sc['title']} | {sc['mood']} | "
                          f"hook: {sc.get('hook', '-')[:30]} | "
                          f"ev={len(sc['events'])} nar={len(sc.get('narration', []))} "
                          f"dlg={len(sc.get('dialogues', []))}")
                return
            print(f"[{attempt+1}/3] unparsable: {content[:150]}")
    sys.exit("adaptation failed")


if __name__ == "__main__":
    asyncio.run(main())
