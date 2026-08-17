#!/usr/bin/env python3
"""工作流 v3（图片版）程序化构建：面向「高质量电商图」交付，无视频环节。

在 v2 基础上：
  - 删除 make-video 节点与 end-video，通过分支直接进「完成-高质量图已生成」
  - 保留 analyze 前置（Top3 卖点红线）、mode 可选、coverage 双条件分支、DeepSeek 容灾
  - 通过分支输出 eval 报告 + coverage，失败分支输出优化建议（LLM 直接可用，无需等配额）

用法: .venv/bin/python dify/build_v3.py
产物: dify/workflow_v3.yml（带断言自检）
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

PARSE_CODE = '''def main(body: str) -> dict:
    rate, cov, top_issue = None, None, ""
    for line in (body or "").splitlines():
        if "总体可用率" in line:
            try:
                rate = float(line.split("总体可用率")[1].split("%")[0].strip())
            except Exception:
                pass
        if "top3_coverage=" in line:
            v = line.split("top3_coverage=")[1].strip()
            cov = None if v == "none" else float(v.replace("%", ""))
        if "top_issue=" in line:
            top_issue = line.split("top_issue=")[1].strip()
    cov_pass = "true" if (cov is None or cov >= 40) else "false"
    return {"rate": rate if rate is not None else -1,
            "coverage": cov if cov is not None else -1,
            "coverage_pass": cov_pass,
            "top_issue": top_issue}'''

LLM_PROMPT = ("你是AI生图质检专家。图片可用率或Top3打穿率未达标，最高频问题是：{{#parse-report.top_issue#}}，"
              "Top3打穿率={{#parse-report.coverage#}}%。请针对该问题给出3条具体可执行的生图Prompt修改建议，"
              "中文，每条一行，确保下一轮生成能在画面中视觉可见地传达Top3卖点。")


def build() -> dict:
    dsl = yaml.safe_load((ROOT / "dify/workflow.yml").read_text(encoding="utf-8"))
    wf = dsl["workflow"]
    graph = wf["graph"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = graph["edges"]

    def shift(node_id: str, dx: int = 300) -> None:
        n = nodes[node_id]
        n["position"]["x"] += dx
        n["positionAbsolute"]["x"] += dx

    # --- 1. start 加 mode ---
    variables = nodes["start"]["data"]["variables"]
    if not any(v["variable"] == "mode" for v in variables):
        variables.append({
            "variable": "mode", "label": "生图模式(styles=风格 / screens=八屏)",
            "type": "select", "required": False, "options": ["styles", "screens"],
            "default": "styles", "max_length": 48,
        })

    # --- 2. analyze 节点 ---
    if "analyze" not in nodes:
        ana = copy.deepcopy(nodes["gen-images"])
        ana["id"] = "analyze"
        ana["position"]["x"] = 350
        ana["positionAbsolute"]["x"] = 350
        ana["data"]["title"] = "前八层分析链(L1→L8)"
        ana["data"]["url"] = "{{#env.API_BASE#}}/analyze/{{#start.product_id#}}?full=false"
        ana["data"]["body"] = {"type": "none", "data": []}
        graph["nodes"].append(ana)
        for e in edges:
            if e["source"] == "start" and e["target"] == "gen-images":
                e["target"] = "analyze"
                e["targetHandle"] = "target"
                e["data"]["targetType"] = "http-request"
                e["id"] = "start-analyze-target"
        edges.append({
            "id": "analyze-gen-images-target", "source": "analyze", "sourceHandle": "source",
            "target": "gen-images", "targetHandle": "target", "type": "custom", "zIndex": 0,
            "selected": False,
            "data": {"isInIteration": False, "isInLoop": False,
                     "sourceType": "http-request", "targetType": "http-request"},
        })

    # 后续节点右移
    for nid in ("gen-images", "eval-images", "parse-report", "check-rate", "make-video",
                "llm-advice", "end-video", "end-advice"):
        if nid in nodes:
            shift(nid, 300)
    nodes["gen-images"]["position"]["x"] = 650
    nodes["gen-images"]["positionAbsolute"]["x"] = 650

    # --- 3. gen-images body 注入 mode ---
    nodes["gen-images"]["data"]["body"] = {
        "type": "json",
        "data": '{"limit": {{#start.gen_limit#}}, "mode": "{{#start.mode#}}"}',
    }

    # --- 4. parse-report 升级 ---
    nodes["parse-report"]["data"]["code"] = PARSE_CODE
    nodes["parse-report"]["data"]["outputs"] = {
        "rate": {"children": None, "type": "number"},
        "coverage": {"children": None, "type": "number"},
        "coverage_pass": {"children": None, "type": "string"},
        "top_issue": {"children": None, "type": "string"},
    }

    # --- 5. check-rate 双条件（ELSE 隐式，不放 cases） ---
    nodes["check-rate"]["data"]["cases"] = [{
        "case_id": "true",
        "logical_operator": "and",
        "conditions": [
            {"id": "cond-rate", "varType": "number",
             "variable_selector": ["parse-report", "rate"],
             "comparison_operator": "≥", "value": "80"},
            {"id": "cond-cov", "varType": "string",
             "variable_selector": ["parse-report", "coverage_pass"],
             "comparison_operator": "is", "value": "true"},
        ],
    }]

    # --- 6. llm-advice 容灾模型 + prompt ---
    nodes["llm-advice"]["data"]["model"] = {
        "provider": "langgenius/openai_api_compatible/openai_api_compatible",
        "name": "deepseek-chat", "mode": "chat",
        "completion_params": {"temperature": 0.3},
    }
    nodes["llm-advice"]["data"]["prompt_template"] = [{"role": "system", "text": LLM_PROMPT}]

    # --- 7. v3 核心：砍掉视频链路 ---
    # 7a. 删 make-video / end-video 节点
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in ("make-video", "end-video")]
    # 7b. true 分支改指 end-images（由 end-video 改造）
    end_images = copy.deepcopy(nodes["end-video"])  # 深拷贝自原节点（此时仍在 nodes dict 里）
    end_images["id"] = "end-images"
    end_images["position"]["x"] = 1600
    end_images["positionAbsolute"]["x"] = 1600
    end_images["data"]["title"] = "完成-高质量电商图"
    end_images["data"]["outputs"] = [
        {"variable": "rate", "value_selector": ["parse-report", "rate"]},
        {"variable": "coverage", "value_selector": ["parse-report", "coverage"]},
        {"variable": "eval_report", "value_selector": ["eval-images", "body"]},
    ]
    graph["nodes"].append(end_images)
    # 7c. 重连边：check-rate true → end-images；删除 make-video 相关节点与边
    graph["edges"] = []
    def edge(eid, src, shandle, tgt, stype, ttype):
        return {"id": eid, "source": src, "sourceHandle": shandle,
                "target": tgt, "targetHandle": "target", "type": "custom", "zIndex": 0,
                "selected": False,
                "data": {"isInIteration": False, "isInLoop": False,
                         "sourceType": stype, "targetType": ttype}}
    graph["edges"] = [
        edge("start-analyze-target", "start", "source", "analyze", "start", "http-request"),
        edge("analyze-gen-images-target", "analyze", "source", "gen-images", "http-request", "http-request"),
        edge("gen-images-eval-images-target", "gen-images", "source", "eval-images", "http-request", "http-request"),
        edge("eval-images-parse-report-target", "eval-images", "source", "parse-report", "http-request", "code"),
        edge("parse-report-check-rate-target", "parse-report", "source", "check-rate", "code", "if-else"),
        edge("check-rate-end-images-target", "check-rate", "true", "end-images", "if-else", "end"),
        edge("check-rate-llm-advice-target", "check-rate", "false", "llm-advice", "if-else", "llm"),
        edge("llm-advice-end-advice-target", "llm-advice", "source", "end-advice", "llm", "end"),
    ]

    # --- 8. end-advice 补 coverage ---
    outs = nodes["end-advice"]["data"]["outputs"]
    if not any(o["variable"] == "coverage" for o in outs):
        outs.append({"variable": "coverage", "value_selector": ["parse-report", "coverage"]})

    dsl["app"]["name"] = "AI高质量电商图流水线 v3"
    dsl["app"]["description"] = ("十一层图片版：前八层分析(Top3红线) → 生图(mode可选) → "
                                 "VLM质检(可用率+Top3打穿率) → 达标出图/未达标优化建议（无视频环节）")
    return dsl


def assert_v3(dsl: dict) -> None:
    graph = dsl["workflow"]["graph"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = graph["edges"]
    problems = []
    ids = set(nodes)
    if "make-video" in ids or "end-video" in ids:
        problems.append("视频节点未清除")
    if "end-images" not in ids:
        problems.append("缺 end-images")
    if not all("source" in e and "target" in e for e in edges):
        problems.append("边字段格式错误")
    for nid in ("analyze", "gen-images", "eval-images"):
        if not isinstance(nodes[nid]["data"].get("timeout"), dict):
            problems.append(f"{nid} timeout 非对象")
    if "mode" not in nodes["gen-images"]["data"]["body"]["data"]:
        problems.append("gen body 缺 mode")
    conds = nodes["check-rate"]["data"]["cases"][0]["conditions"]
    if len(conds) != 2 or conds[0]["comparison_operator"] != "≥":
        problems.append("check-rate 条件不对")
    if any(len(c.get("conditions", [1])) == 0 for c in nodes["check-rate"]["data"]["cases"]):
        problems.append("存在空 conditions 的 case（会触发 ELIF 警告）")
    if nodes["llm-advice"]["data"]["model"]["name"] != "deepseek-chat":
        problems.append("llm 模型未切换")
    pairs = {(e["source"], e["target"]) for e in edges}
    for pair in [("start", "analyze"), ("analyze", "gen-images"), ("gen-images", "eval-images"),
                 ("eval-images", "parse-report"), ("parse-report", "check-rate"),
                 ("check-rate", "end-images"), ("check-rate", "llm-advice"),
                 ("llm-advice", "end-advice")]:
        if pair not in pairs:
            problems.append(f"缺边 {pair}")
    if problems:
        for p in problems:
            print(f"[v3] ✗ {p}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    dsl = build()
    assert_v3(dsl)
    out = ROOT / "dify/workflow_v3.yml"
    out.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"[v3] ✓ {len(dsl['workflow']['graph']['nodes'])}节点 → {out}")


if __name__ == "__main__":
    main()
