#!/usr/bin/env python3
"""00_clean 规则清洗:NovelForge 章节原文 -> 干净正文(无作者插话/表情注释/空行)。

规则清洗(零成本、确定性)放 LLM 改编前——LLM 只做节奏改编,不做垃圾清理,
各司其职防止 LLM 清洗不稳定/漏删/误删。
输出 vampire_clean.txt,喂给 00_adapt。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "comic"

# 1) 作者插话行(整行删)——精确锚点,宁缺勿滥,防止误删正文
AUTHOR_LINE_RE = re.compile(
    r"^(书刚开|吸血鬼这么罕见|脑子寄存处|评论领取异能|"
    r"求收藏|求票|求月票|月票|加更规则|章节评论|新书期|各位读者|本书书友|"
    r"感谢.*打赏|读者大大).*?$",
    re.M,
)
# 2) 表情包注释(括号内含 .jpg/.png/狗头/保熟/大拇哥/勉为其难 等,TTS 会念出来)
EMOJI_NOTE_RE = re.compile(
    r"[（(][^（）()]{0,14}"
    r"(?:\.jpg|\.png|\.gif|狗头|保熟|大拇哥|勉为其难|捂脸|白眼|滑稽|偷笑|流汗)"
    r"[^（）()]*[)）]"
)
# 3) 「重写/调整:」残渣锚点(取最后一次之后的正文=最终稿)
REWRITE_ANCHOR = "重写/调整"


def clean(raw: str) -> str:
    # NovelForge 导出可能带 \r
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # LLM 思考残渣:取最后一次「重写/调整:」之后
    lines = raw.split("\n")
    idx = None
    for i, l in enumerate(lines):
        if l.strip().startswith(REWRITE_ANCHOR):
            idx = i + 1
    if idx is not None:
        raw = "\n".join(lines[idx:])

    # 尾部自检残渣(（本文共xx字）之类)
    raw = re.sub(r"\n（[^）]*字[^）]*）.*$", "", raw, flags=re.S)

    raw = AUTHOR_LINE_RE.sub("", raw)
    raw = EMOJI_NOTE_RE.sub("", raw)
    # 空行压缩
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return "\n".join(l.rstrip() for l in raw.split("\n")).strip() + "\n"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "vampire_raw.txt"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_DIR / "vampire_clean.txt"
    raw = src.read_text(encoding="utf-8")
    body = clean(raw)

    removed = [l for l in raw.split("\n") if AUTHOR_LINE_RE.match(l)]
    print(f"{src.name} -> {dst.name}")
    print(f"  raw {len(raw)} chars -> clean {len(body)} chars "
          f"| 删作者行 {len(removed)} | 删表情注释 {len(EMOJI_NOTE_RE.findall(raw))}")
    for l in removed:
        print(f"  - {l[:50]}")
    dst.write_text(body, encoding="utf-8")
    print(f"OK -> {dst}")


if __name__ == "__main__":
    main()
