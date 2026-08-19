#!/usr/bin/env python3
"""清洗 NovelForge 导出的章节正文:剥离 LLM 生成时的思考残渣/重复扩写。"""
import re
import sys

RAW = "/Users/Admin/Desktop/dify-pipeline/output/comic/ch1_raw.txt"
OUT = "/Users/Admin/Desktop/dify-pipeline/output/comic/ch1_clean.txt"

raw = open(RAW, encoding="utf-8").read()
lines = raw.split("\n")

# 找最后一次「重写/调整：」之后的正文(那是最终版)
idx = None
for i, l in enumerate(lines):
    if l.strip().startswith("重写/调整"):
        idx = i + 1
if idx is None:
    sys.exit("anchor not found")

body = "\n".join(lines[idx:]).strip()
# 去掉尾部自检残渣
body = re.sub(r"\n（[^）]*字[^）]*）.*$", "", body, flags=re.S)
# 中英文引号统一、去行尾空白
body = "\n".join(l.rstrip() for l in body.split("\n")).strip() + "\n"

open(OUT, "w", encoding="utf-8").write(body)
print("chars:", len(body))
print("head:", body[:200])
print("tail:", body[-200:])
