#!/usr/bin/env python3
"""识图模型测评：claude-opus-4-6 vs gemini-3-flash vs gpt-5.2-codex(或替补)。

真值策略：客观题程序判分（关键词精确匹配+颜色归一化），主观题输出人工裁决页。
题源：dify-pipeline T001 bundle 真实产物。
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLE = ROOT / "output" / "bundles" / "T001_shein_official_v1"
PROXY = "http://127.0.0.1:7897"
KEY = None  # __main__ 里从 .env 读


# ── 模型适配器 ──────────────────────────────────────────────

def ask_claude(model, imgs, q, timeout=180):
    content = []
    for p in imgs:
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": b64}})
    content.append({"type": "text", "text": q})
    r = httpx.post("https://api.apimart.ai/v1/messages",
                   headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
                   json={"model": model, "max_tokens": 2000, "messages": [
                       {"role": "user", "content": content}]},
                   proxy=PROXY, timeout=timeout)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


GEMINI_ACTUAL = {"name": "gemini-3-flash-preview", "degraded": False}


def ask_gemini(model, imgs, q, timeout=180):
    """gemini-3-flash 优先；503 时自动降级 gemini-2.5-flash（标注 degraded）。"""
    try:
        return ask_openai_chat(GEMINI_ACTUAL["name"], imgs, q, timeout)
    except Exception:
        if "3" in GEMINI_ACTUAL["name"]:
            GEMINI_ACTUAL.update(name="gemini-2.5-flash", degraded=True)
            print("  [gemini] 3-flash 不可用 → 降级 2.5-flash")
            return ask_openai_chat(GEMINI_ACTUAL["name"], imgs, q, timeout)
        raise


def ask_openai_chat(model, imgs, q, timeout=180):
    content = [{"type": "text", "text": q}]
    for p in imgs:
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + b64}})
    r = httpx.post("https://api.apimart.ai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {KEY}"},
                   json={"model": model, "stream": False, "max_tokens": 2000,
                         "messages": [{"role": "user", "content": content}]},
                   proxy=PROXY, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask_openai_responses(model, imgs, q, timeout=180):
    content = [{"type": "input_text", "text": q}]
    for p in imgs:
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        content.append({"type": "input_image",
                        "image_url": "data:image/png;base64," + b64})
    r = httpx.post("https://api.apimart.ai/v1/responses",
                   headers={"Authorization": f"Bearer {KEY}"},
                   json={"model": model, "input": [
                       {"role": "user", "content": content}]},
                   proxy=PROXY, timeout=timeout)
    r.raise_for_status()
    return r.json()["output"][-1]["content"][0]["text"]


MODELS = {}  # __main__ 里注册


def with_retry(fn, *a, retries=3, timeout_cap=180, **kw):
    last = None
    for i in range(retries):
        try:
            return fn(*a, timeout=timeout_cap, **kw)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(8 * (i + 1))
    return f"__FAIL__ {last}"[:200]


def _clean(a: str) -> str:
    """判分前清洗：剥 markdown 星号/井号、空白；撇号归一。"""
    a = a.replace("*", "").replace("#", "").replace("’", "'")
    a = a.replace("IDON'T", "I DON'T").replace("IDONT", "I DON'T")
    return a.strip()


def _norm_ocr(a: str) -> str:
    """OCR 空格无关匹配。"""
    return re.sub(r"[^A-Z']", "", _clean(a).upper().replace(" ", "").replace("?", ""))


# ── 题库（真值 = 程序可测/人工金标）────────────────────────



# ── 人脸专项题库 v2（题源: 事例1 真实人脸 + T001 模特图）─────

EX1 = ROOT / "output" / "images" / "事例1"
EX1_FACES = ["0c347cde-ccf4-44c9-9b47-d9701b2508ad.png",
             "f1ae19d9-4ced-4103-94bc-d298bf42ddfb.png",
             "f9e2f3dd-89fa-4491-a996-0887cf06ca58.png"]


def build_face_questions():
    g = lambda n: str(BUNDLE / f"T001_{n}.png")
    e = lambda n: str(EX1 / n)
    return [
        dict(id="FACE-E", dim="人脸", diff=1, imgs=[e(n) for n in EX1_FACES],
             q="三张图中的女性是否同一个人？从脸型/五官/发型/肤色判断。第一词作答：同一人/不同人，然后一句依据。",
             type="human", gold="用户裁决（claude曾判不同人,codex倾向同人——争议题）"),
        dict(id="FACE-M", dim="人脸", diff=2, imgs=[e(EX1_FACES[0]), g("01_户外街拍穿搭图")],
             q="两张图的模特是否同一个人？答：同一人/不同人+一句依据。",
             type="auto", check=lambda a: _clean(a).startswith("不同人"),
             gold="不同人(跨人物负向对照)"),
        dict(id="FACE-H", dim="人脸", diff=3,
             imgs=[e(n) for n in EX1_FACES] + [g("00B_模特三视图")],
             q="四张图（前3张真实照片，第4张AI三视图）。第4张三视图里的模特与前3张照片里的女性是否同一人？答：同一人/不同人+依据。",
             type="auto", check=lambda a: _clean(a).startswith("不同人"),
             gold="不同人(真照片vs AI模特)"),
        dict(id="FACE-XM", dim="人脸", diff=2,
             imgs=[g(n) for n in ["01_户外街拍穿搭图", "06_模特局部穿搭图", "07_夜景街拍图"]],
             q="三张AI生成电商图的模特是否同一人？发型/脸型/肤色判断，答：同一人/不同人+指出最不像的一张(1/2/3)。",
             type="human", gold="用户裁决(AI生成,已知基本一致但05不在其中)"),
        dict(id="FACE-D1", dim="人脸细节", diff=3, imgs=[e(EX1_FACES[0])],
             q="描述这位女性的脸：脸型/眼形/眉形/鼻型/唇形各一个词，共5词。",
             type="human", gold="用户裁决(考察描述精度与幻觉)"),
        dict(id="FACE-D2", dim="人脸细节", diff=2, imgs=[e(EX1_FACES[2])],
             q="她的情绪状态是什么？眼神方向看向哪里？15字内。",
             type="human", gold="用户裁决"),
    ]



# ── 718 成品图专项（用户作品题源：ChatGPT 生成人像）─────

P718 = Path("/Users/Admin/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
            "xwechat_files/wxid_pazv0uyu05sy22_4915/msg/file/2026-08/"
            "618 白棕色 白底图/718 成品图")
G_A = ["ChatGPT Image 2026年8月14日 13_55_42.png", "ChatGPT Image 2026年8月14日 14_00_17.png",
       "ChatGPT Image 2026年8月14日 14_03_32.png", "ChatGPT Image 2026年8月14日 14_04_28.png"]
G_B = ["ChatGPT Image 2026年8月14日 13_55_06.png", "ChatGPT Image 2026年8月14日 14_05_43.png",
       "ChatGPT Image 2026年8月14日 14_08_59.png"]
G_USER3 = ["ChatGPT Image 2026年8月14日 14_30_23 (1).png",
           "ChatGPT Image 2026年8月14日 14_30_23 (2).png",
           "ChatGPT Image 2026年8月14日 14_30_23 (3).png"]


def build_718_questions():
    e = lambda n: str(P718 / n)
    return [
        dict(id="W-A4", dim="同人判定", diff=1, imgs=[e(n) for n in G_A],
             q="四张图的模特是否同一个人？答：同一人/不同人+一句依据。",
             type="auto", check=lambda a: _clean(a).startswith("同一人"),
             gold="同一人(米白T系列,claude已验)"),
        dict(id="W-B3", dim="同人判定", diff=2, imgs=[e(n) for n in G_B],
             q="三张图的模特是否同一个人？答：同一人/不同人+一句依据。",
             type="auto", check=lambda a: _clean(a).startswith("同一人"),
             gold="同一人(粉吊带系列,claude已验)"),
        dict(id="W-U3", dim="异人判定", diff=2, imgs=[e(n) for n in G_USER3],
             q="三张图的模特是否同一个人？若不同，各有几个人？答：同一人/不同人(人数)+依据。",
             type="auto", check=lambda a: "不同人" in _clean(a) and "3" in _clean(a)[:30],
             gold="不同人(3人:波波头/眼镜低扎/长卷发)"),
        dict(id="W-AB", dim="异人判定", diff=3,
             imgs=[e(G_A[0]), e(G_B[0])],
             q="两张图的模特是否同一个人？答：同一人/不同人+关键差异。",
             type="auto", check=lambda a: _clean(a).startswith("不同人"),
             gold="不同人(A群米白T vs B群粉吊带)"),
        dict(id="W-MIX", dim="混合找茬", diff=3,
             imgs=[e(G_A[0]), e(G_A[1]), e(G_USER3[0]), e(G_USER3[2])],
             q="四张图里有几个不同的人？指出哪几张是同一人(编号1-4)。",
             type="human", gold="2组:1+2同人,3+4各独立(共3人)——用户裁决"),
        dict(id="W-D", dim="人脸细节", diff=3, imgs=[e(G_A[2])],
             q="描述这位模特：脸型/眼形/发型发色/肤色/情绪，各一个词，共5词。",
             type="human", gold="用户裁决(长卷深棕发/米白T那张)"),
    ]

def build_questions():
    g = lambda n: str(BUNDLE / f"T001_{n}.png")
    return [
        # D1 OCR
        dict(id="OCR-E", dim="OCR", diff=1, imgs=[g("00A_商品标准特写")],
             q="T恤胸口印花文字逐字母精确转写(含撇号)。只输出文字本身。",
             type="auto", check=lambda a: _norm_ocr(a) == "SMKEIDON'T".replace(" ", "") or "SMOKEIDON'T" in _norm_ocr(a),
             gold="SMOKE I DON'T"),
        dict(id="OCR-M", dim="OCR", diff=2, imgs=[g("01_户外街拍穿搭图")],
             q="T恤胸口印花文字逐字母精确转写(含撇号)。只输出文字本身。",
             type="auto", check=lambda a: _norm_ocr(a) == "SMKEIDON'T".replace(" ", "") or "SMOKEIDON'T" in _norm_ocr(a),
             gold="SMOKE I DON'T"),
        dict(id="OCR-H", dim="OCR", diff=3, imgs=[g("06_模特局部穿搭图")],
             q="T恤上所有可见文字逐字母精确转写，多个用|分隔。只输出文字。",
             type="auto", check=lambda a: "SMOKE" in _norm_ocr(a),
             gold="SMOKE(可见部分)"),
        # D2 颜色
        dict(id="CLR-E", dim="颜色", diff=1, imgs=[g("00A_商品标准特写")],
             q="T恤底色和印花颜色各是什么？格式：底色X/印花Y，各5字内。",
             type="auto", check=lambda a: ("黄" in _clean(a)) and ("粉" in _clean(a) or "玫" in _clean(a) or "红" in _clean(a)),
             gold="底色淡黄/印花粉红做旧(人工核)"),
        dict(id="CLR-M", dim="颜色", diff=2, imgs=[g("07_夜景街拍图")],
             q="夜景灯光下，T恤的真实底色是什么？排除灯光偏色。5字内。",
             type="auto", check=lambda a: "黄" in _clean(a), gold="黄(系)"),
        dict(id="CLR-H", dim="颜色", diff=3,
             imgs=[g("01_户外街拍穿搭图"), g("05_场景种草图")],
             q="两图T恤印花颜色是否相同？答：相同/轻微差异/明显不同+一句理由。",
             type="human", gold="人工裁决(gpt-5.2-pro 曾判:轻微色差)"),
        # D3 人物一致性
        dict(id="PER-E", dim="人物", diff=1, imgs=[g("00B_模特三视图")],
             q="图中三个视图是否同一人同一套衣服？答：是/否+一处依据。",
             type="auto", check=lambda a: _clean(a).startswith("是"),
             gold="是"),
        dict(id="PER-M", dim="人物", diff=2,
             imgs=[g("01_户外街拍穿搭图"), g("06_模特局部穿搭图")],
             q="两图模特是否同一人？发型/脸型/肤色判断。答：同一人/不同人。",
             type="human", gold="人工裁决"),
        dict(id="PER-H", dim="人物", diff=3,
             imgs=[g(n) for n in ["01_户外街拍穿搭图", "02_户外场景种草图",
                                  "05_场景种草图", "06_模特局部穿搭图", "07_夜景街拍图"]],
             q="五张图模特是否同一人？若不是，指出第几张是outlier(编号1-5)。",
             type="human", gold="人工裁决(已知:05发丝微卷是弱outlier)"),
        # D4 商品一致性
        dict(id="PRD-E", dim="商品", diff=1,
             imgs=[g("01_户外街拍穿搭图"), g("03_白底单品图")],
             q="两图T恤是否同一款(颜色/印花/版型)？答：是/否。",
             type="auto", check=lambda a: _clean(a).startswith("是"), gold="是"),
        dict(id="PRD-H", dim="商品", diff=3, imgs=[g("00B_模特三视图")],
             q="三视图的三个视图服装是否完全一致？若有差异逐项列出(视图/差异)。",
             type="human", gold="人工裁决"),
        # D5 抗幻觉
        dict(id="HAL-E", dim="抗幻觉", diff=1, imgs=[g("00A_商品标准特写")],
             q="这张图里有几只猫？只答数字。",
             type="auto", check=lambda a: _clean(a).startswith("0"), gold="0"),
        dict(id="HAL-H", dim="抗幻觉", diff=3, imgs=[g("01_户外街拍穿搭图")],
             q="列出T恤上的所有图案元素(逐项)。没有的不要编造。",
             type="human", gold="应只有SMOKE印花文字,编造徽标/动物/装饰=幻觉"),
    ]


# ── 主流程 ──────────────────────────────────────────────────

def main():
    global KEY
    import re
    env = (ROOT / ".env").read_text()
    KEY = re.search(r"^ARK_API_KEY=(.+)$", env, re.M).group(1).strip()

    # 参赛注册（gpt-5.2-codex 忙则替补 gpt-5.3-codex）
    def probe_codex():
        try:
            r = ask_openai_responses("gpt-5.2-codex", [], "reply: ok", timeout=60)
            return "gpt-5.2-codex"
        except Exception:
            return "gpt-5.3-codex"
    codex_id = probe_codex()
    MODELS.clear()
    MODELS.update({
        "claude-opus-4-6": ask_claude,
        "gemini-3-flash(降级2.5)": ask_gemini,
        codex_id: ask_openai_responses,
    })
    print(f"[Bench] codex 选手: {codex_id}")

    import sys
    mode = next((a for a in sys.argv[1:] if a.startswith("--")), "")
    if mode == "--face":
        questions = build_face_questions()
    elif mode == "--718":
        questions = build_718_questions()
    else:
        questions = build_questions()
    print(f"[Bench] 模式: {mode or '商品全维度'}")
    results = {m: [] for m in MODELS}
    for q in questions:
        for mid, fn in MODELS.items():
            t0 = time.time()
            ans = with_retry(fn, mid, q["imgs"], q["q"])
            dt = round(time.time() - t0, 1)
            ok = None
            if q["type"] == "auto":
                ok = bool(q["check"](ans)) if not ans.startswith("__FAIL__") else False
            results[mid].append({"qid": q["id"], "dim": q["dim"], "diff": q["diff"],
                                 "ans": ans[:300], "ok": ok, "sec": dt,
                                 "type": q["type"]})
            tag = "?" if ok is None else ("✓" if ok else "✗")
            print(f"  {tag} {q['id']:<6} {mid:<18} {dt:>5}s {ans[:40]!r}")

    out = ROOT / "data" / "bench_results.json"
    out.write_text(json.dumps(
        {"models": list(MODELS), "results": results,
         "questions": [{k: v for k, v in q.items() if k != "check"} for q in questions]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Bench] 结果 → {out}")

    # 汇总(客观题)
    print("\n== 客观题得分(满分12) ==")
    for mid, rows in results.items():
        auto = [r for r in rows if r["type"] == "auto"]
        score = sum(r["diff"] for r in auto if r["ok"])
        print(f"  {mid:<20} {score}/12  ({sum(1 for r in auto if r['ok'])}/{len(auto)}题)")
    print("\n== 平均延迟 ==")
    for mid, rows in results.items():
        print(f"  {mid:<20} {sum(r['sec'] for r in rows)/len(rows):.1f}s")


if __name__ == "__main__":
    main()
