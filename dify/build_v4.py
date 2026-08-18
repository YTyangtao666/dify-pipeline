#!/usr/bin/env python3
"""工作流 v4（技能包版）：技能包 × 商品素材 → 双锚定批量生成 → 图片清单。

用法: .venv/bin/python dify/build_v4.py
产物: dify/workflow_v4.yml（带断言自检）
依赖: 本机 api_server(8100) + 已学习的技能包 + 商品素材
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

POLL_CODE = (
    "def main(task_id: str) -> dict:\n"
    "    import time, json, urllib.request\n"
    "    imgs, state, summary = [], 'timeout', {}\n"
    "    for _ in range(17):  # 16x30s = 8min + margin\n"
    "        try:\n"
    "            req = urllib.request.Request('http://127.0.0.1:8100/tasks/' + task_id)\n"
    "            with urllib.request.urlopen(req, timeout=10) as r:\n"
    "                t = json.loads(r.read().decode())\n"
    "            state = t.get('state', '?')\n"
    "            if state in ('done', 'failed'):\n"
    "                imgs = [i['url'] for i in t.get('images', [])]\n"
    "                summary = t.get('summary', {})\n"
    "                break\n"
    "        except Exception:\n"
    "            pass\n"
    "        time.sleep(30)\n"
    "    n = len(imgs)\n"
    "    nl = chr(10)\n"
    "    return {'state': state, 'image_count': n,\n"
    "            'images_text': nl.join('http://127.0.0.1:8100' + u for u in imgs),\n"
    "            'summary_text': json.dumps(summary, ensure_ascii=False)}\n"
)


def build() -> dict:
    dsl = yaml.safe_load((ROOT / "dify/workflow.yml").read_text(encoding="utf-8"))
    wf = dsl["workflow"]
    nodes, edges = [], []
    nodes.append({
        "id": "start", "position": {"x": 50, "y": 280}, "positionAbsolute": {"x": 50, "y": 280},
        "sourcePosition": "right", "targetPosition": "left", "width": 244, "height": 120,
        "data": {"type": "start", "title": "开始", "desc": "填技能包ID与商品ID",
                 "variables": [
                     {"variable": "skill_id", "label": "技能包ID", "type": "text-input",
                      "required": True, "max_length": 100, "default": "shein_official_v1",
                      "options": []},
                     {"variable": "product_id", "label": "商品ID", "type": "text-input",
                      "required": True, "max_length": 100, "default": "T001",
                      "options": []}]}})
    nodes.append({
        "id": "submit", "position": {"x": 350, "y": 280}, "positionAbsolute": {"x": 350, "y": 280},
        "sourcePosition": "right", "targetPosition": "left", "width": 244, "height": 120,
        "data": {"type": "http-request", "title": "提交生成任务",
                 "desc": "POST /generate/skill/async",
                 "method": "post", "url": "http://127.0.0.1:8100/generate/skill/async",
                 "authorization": {"type": "no-auth", "config": None},
                 "headers": 'Content-Type:application/json',
                 "params": "",
                 "body": '{"skill_id": "{{#start.skill_id#}}", "product_id": "{{#start.product_id#}}"}',
                 "timeout": {"max_connect_timeout": 10, "max_read_timeout": 60,
                             "max_write_timeout": 20, "max_exec_timeout": 70}}})
    nodes.append({
        "id": "poll", "position": {"x": 650, "y": 280}, "positionAbsolute": {"x": 650, "y": 280},
        "sourcePosition": "right", "targetPosition": "left", "width": 244, "height": 120,
        "data": {"type": "code", "title": "轮询至完成",
                 "desc": "每30s轮询，最长8.5分钟",
                 "variables": [{"variable": "task_id", "value_selector": ["submit", "body", "task_id"]}],
                 "code_language": "python3", "code": POLL_CODE,
                 "outputs": {"state": {"type": "string"}, "image_count": {"type": "number"},
                             "images_text": {"type": "string"},
                             "summary_text": {"type": "string"}}}})
    nodes.append({
        "id": "end", "position": {"x": 950, "y": 280}, "positionAbsolute": {"x": 950, "y": 280},
        "targetPosition": "left", "width": 244, "height": 120,
        "data": {"type": "end", "title": "完成",
                 "outputs": [{"variable": "state", "value_selector": ["poll", "state"]},
                             {"variable": "image_count", "value_selector": ["poll", "image_count"]},
                             {"variable": "images", "value_selector": ["poll", "images_text"]},
                             {"variable": "summary", "value_selector": ["poll", "summary_text"]}]}})
    edges += [{"id": "e1", "source": "start", "sourceHandle": "source", "target": "submit",
               "targetHandle": "target", "type": "custom", "zIndex": 0},
              {"id": "e2", "source": "submit", "sourceHandle": "source", "target": "poll",
               "targetHandle": "target", "type": "custom", "zIndex": 0},
              {"id": "e3", "source": "poll", "sourceHandle": "source", "target": "end",
               "targetHandle": "target", "type": "custom", "zIndex": 0}]
    wf["graph"] = {"nodes": nodes, "edges": edges}
    wf["features"] = {}
    dsl["app"] = {"name": "AI电商图工厂 v4 · 技能包一键生成", "mode": "workflow",
                  "icon": "\U0001F5BC️", "description":
                  "技能包×商品 → 双锚定批量生成(商品特写+模特三视图+套图)，异步任务+轮询"}
    return dsl


def self_check(dsl: dict) -> None:
    g = dsl["workflow"]["graph"]
    ids = [n["id"] for n in g["nodes"]]
    assert ids == ["start", "submit", "poll", "end"], ids
    assert len(g["edges"]) == 3
    code = next(n for n in g["nodes"] if n["id"] == "poll")["data"]["code"]
    assert "127.0.0.1:8100/tasks" in code and "time.sleep(30)" in code
    start_vars = g["nodes"][0]["data"]["variables"]
    assert {v["variable"] for v in start_vars} == {"skill_id", "product_id"}
    print("v4 self-check OK")


if __name__ == "__main__":
    d = build()
    self_check(d)
    out = ROOT / "dify/workflow_v4.yml"
    out.write_text(yaml.dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"-> {out}")
