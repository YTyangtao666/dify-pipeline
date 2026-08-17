#!/usr/bin/env python3
"""工作流 v2 程序化构建：在 dify/workflow.yml（DB 验证版）基础上注入十一层编排。

变更清单（相对 v1）:
  1. start 加 mode 变量（styles|screens）
  2. 新增 analyze 节点（L1→L8 分析链前置，Top3 红线）
  3. gen-images body 注入 mode
  4. parse-report 解析 top3_coverage，输出 coverage/coverage_pass
  5. check-rate 双条件：rate≥80 AND coverage_pass=true
  6. llm-advice 换 deepseek-chat 官方直连（容灾），prompt 注入 coverage
  7. 两个 end 节点补 coverage 输出
产物: dify/workflow_v2.yml（带断言自检，失败即退出）
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

    # --- 2. analyze 节点（v1 gen-images 克隆改） ---
    if "analyze" not in nodes:
        ana = copy.deepcopy(nodes["gen-images"])
        ana["id"] = "analyze"
        ana["position"]["x"] = 350
        ana["positionAbsolute"]["x"] = 350
        ana["data"]["title"] = "前八层分析链(L1→L8)"
        ana["data"]["url"] = "{{#env.API_BASE#}}/analyze/{{#start.product_id#}}?full=false"
        ana["data"]["body"] = {"type": "none", "data": []}
        graph["nodes"].append(ana)
        # gen-images 前插入 analyze：start→analyze→gen
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

    # --- 5. check-rate 双条件 ---
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
    }, {"case_id": "false", "conditions": []}]

    # --- 6. llm-advice 容灾模型 + prompt ---
    nodes["llm-advice"]["data"]["model"] = {
        "provider": "langgenius/openai_api_compatible/openai_api_compatible",
        "name": "deepseek-chat", "mode": "chat",
        "completion_params": {"temperature": 0.3},
    }
    nodes["llm-advice"]["data"]["prompt_template"] = [{"role": "system", "text": LLM_PROMPT}]

    # --- 7. end 节点补 coverage ---
    nodes["end-video"]["data"]["outputs"].append(
        {"variable": "coverage", "value_selector": ["parse-report", "coverage"]})
    nodes["end-advice"]["data"]["outputs"].append(
        {"variable": "coverage", "value_selector": ["parse-report", "coverage"]})

    # app 名与描述
    dsl["app"]["name"] = "AI商品图视频流水线 v2"
    dsl["app"]["description"] = "十一层编排：前八层分析(Top3红线) → 生图(mode可选) → VLM质检(可用率+Top3打穿率) → 视频合成/优化建议"
    return dsl


def assert_v2(dsl: dict) -> None:
    graph = dsl["workflow"]["graph"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = graph["edges"]
    problems = []
    if not all("source" in e and "target" in e for e in edges):
        problems.append("边字段格式错误")
    for nid in ("analyze", "gen-images", "eval-images", "make-video"):
        t = nodes[nid]["data"].get("timeout")
        if not isinstance(t, dict):
            problems.append(f"{nid} timeout 非对象")
    if nodes["gen-images"]["data"]["body"]["data"].find("mode") < 0:
        problems.append("gen body 缺 mode")
    conds = nodes["check-rate"]["data"]["cases"][0]["conditions"]
    if len(conds) != 2 or conds[0]["comparison_operator"] != "≥":
        problems.append("check-rate 条件不对")
    if nodes["llm-advice"]["data"]["model"]["name"] != "deepseek-chat":
        problems.append("llm 模型未切换")
    # 连通性: start→analyze→gen→eval→parse→check→(video|llm)→end
    pairs = {(e["source"], e["target"]) for e in edges}
    for pair in [("start", "analyze"), ("analyze", "gen-images"), ("gen-images", "eval-images"),
                 ("eval-images", "parse-report"), ("parse-report", "check-rate"),
                 ("check-rate", "make-video"), ("check-rate", "llm-advice"),
                 ("make-video", "end-video"), ("llm-advice", "end-advice")]:
        if pair not in pairs:
            problems.append(f"缺边 {pair}")
    if problems:
        for p in problems:
            print(f"[v2] ✗ {p}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    dsl = build()
    assert_v2(dsl)
    out = ROOT / "dify/workflow_v2.yml"
    out.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding="utf-8")
    n = len(dsl["workflow"]["graph"]["nodes"])
    print(f"[v2] ✓ {n}节点 → {out}")


if __name__ == "__main__":
    main()
