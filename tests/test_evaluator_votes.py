"""VLM 多票表决测试：判定稳定性（概率性输出 → 3票多数决）"""
import base64
import json

import httpx
import pytest
import respx

from scripts.pipeline.config import Config

BASE = "https://yunwu.test/v1"
ZHIPU = "https://open.bigmodel.test/v4"


def make_cfg(tmp_path, **kw):
    d = dict(base_url=BASE, api_key="sk-t", image_model="m",
             vlm_model="gemini-3.5-flash", llm_model="llm", out_dir=tmp_path,
             vlm_fallback_url=ZHIPU, vlm_fallback_key="zp",
             vlm_fallback_model="glm-4v-flash")
    d.update(kw)
    return Config(**d)


def tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def resp(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class TestMajorityVote:
    async def test_three_votes_majority_wins(self, tmp_path, monkeypatch):
        """3 次调用输出波动（true/true/false）→ hit 按多数决 = true"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path, eval_votes=3)
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())

        outputs = [
            json.dumps({"usable": True, "score": 90, "issues": [],
                        "top3_hits": [{"point": "p1", "hit": True}]}),
            json.dumps({"usable": True, "score": 90, "issues": [],
                        "top3_hits": [{"point": "p1", "hit": True}]}),
            json.dumps({"usable": True, "score": 90, "issues": [],
                        "top3_hits": [{"point": "p1", "hit": False}]}),
        ]
        state = {"i": 0}

        def route(request):
            o = outputs[state["i"] % len(outputs)]
            state["i"] += 1
            return resp(o)

        with respx.mock(assert_all_called=False) as m:
            m.post(f"{BASE}/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            m.post(f"{ZHIPU}/chat/completions").mock(side_effect=route)
            v = await evaluator.evaluate_image(cfg, img, "保温杯")

        assert state["i"] == 3
        assert v.top3_hits[0]["hit"] is True  # 2/3 多数

    async def test_votes_merge_score_by_median(self, tmp_path, monkeypatch):
        """分数取中位数（90/100/80 → 90）"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path, eval_votes=3)
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())
        scores = [90, 100, 80]
        state = {"i": 0}

        def route(request):
            s = scores[state["i"] % 3]
            state["i"] += 1
            return resp(json.dumps({"usable": True, "score": s, "issues": [],
                                    "top3_hits": []}))

        with respx.mock(assert_all_called=False) as m:
            m.post(f"{BASE}/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            m.post(f"{ZHIPU}/chat/completions").mock(side_effect=route)
            v = await evaluator.evaluate_image(cfg, img, "保温杯")

        assert v.score == 90

    async def test_single_vote_default(self, tmp_path, monkeypatch):
        """默认 1 票（eval_votes 缺省）——行为不变"""
        from scripts.pipeline import evaluator

        cfg = make_cfg(tmp_path)
        assert cfg.eval_votes == 1
        monkeypatch.setattr(evaluator.asyncio, "sleep", _no_sleep)
        img = tmp_path / "a.png"
        img.write_bytes(tiny_png())
        with respx.mock(assert_all_called=False) as m:
            m.post(f"{BASE}/chat/completions").mock(
                return_value=httpx.Response(403, json={"error": {"code": "local:insufficient_quota"}}))
            m.post(f"{ZHIPU}/chat/completions").mock(side_effect=lambda r: resp(
                json.dumps({"usable": True, "score": 95, "issues": []})))
            v = await evaluator.evaluate_image(cfg, img, "保温杯")
        assert v.score == 95


async def _no_sleep(s):
    return None
