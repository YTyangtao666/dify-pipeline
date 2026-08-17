#!/usr/bin/env python3
"""从 Dify DB 导出已验证可跑的 workflow graph → dify/workflow.yml（仓库自包含可用）。

用法: .venv/bin/python dify/export_graph.py
断言自检失败即非零退出（防止毒药格式再次回写）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_ID = "ec72f9e7-5384-4591-8b28-aeb054adf9a5"  # 2026-08-15 发布的 E2E 验证版

HTTP_NODES = ("analyze", "gen-images", "eval-images", "make-video")


def fetch_graph() -> dict:
    q = f"SELECT graph FROM workflows WHERE id='{WORKFLOW_ID}';"
    r = subprocess.run(
        ["docker", "exec", "docker-db-1", "psql", "-U", "postgres", "-d", "dify", "-t", "-A", "-c", q],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip())


def assert_graph(graph: dict) -> None:
    edges = graph["edges"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    problems = []
    if not all("source" in e and "target" in e for e in edges):
        problems.append("边字段不是 source/target（旧格式毒药）")
    for nid in HTTP_NODES:
        if nid not in nodes:
            continue
        t = nodes[nid]["data"].get("timeout")
        if not isinstance(t, dict):
            problems.append(f"{nid} timeout 不是对象: {t!r}")
    cond = nodes["check-rate"]["data"]["cases"][0]["conditions"][0]
    if cond["comparison_operator"] != "≥":
        problems.append(f"比较符不是 unicode: {cond['comparison_operator']!r}")
    if problems:
        for p in problems:
            print(f"[export] ✗ {p}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    graph = fetch_graph()
    assert_graph(graph)
    dsl = {
        "kind": "app",
        "version": "0.1.5",
        "app": {
            "name": "AI商品图视频流水线",
            "mode": "workflow",
            "description": "商品图生成 → VLM质检 → 自动视频合成 全链路",
            "icon": "🤖",
            "icon_background": "#FFEAD5",
            "use_icon_as_answer_icon": False,
        },
        "workflow": {
            "graph": graph,
            "features": {"file_upload": {"enabled": False}},
            "environment_variables": [{
                "id": "api-base-env", "name": "API_BASE",
                "value": "http://host.docker.internal:8100", "value_type": "string",
                "selector": [],
                "description": "FastAPI服务地址（Dify在Docker内，宿主服务用host.docker.internal）",
            }],
            "conversation_variables": [],
        },
    }
    out = ROOT / "dify/workflow.yml"
    out.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"[export] ✓ {len(graph['nodes'])}节点 {len(graph['edges'])}边 → {out}")


if __name__ == "__main__":
    main()
