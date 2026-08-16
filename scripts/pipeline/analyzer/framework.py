"""L5 框架库：拆解规律沉淀为可复用框架，带 score（L11 数据回流唯一入口）。

方法论（十一层·第五层）：框架库不是一次性资产——平台风格、买家审美、同行打法都会变，
昨天的爆款框架不能硬套今天。score 由投放数据驱动更新（红线2：单向数据流）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import storyboard

EIGHT_SCREEN_ID = "fw_8screen_v1"
RETIRE_WIN_RATE = 0.25


class FrameworkLibrary:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {"frameworks": []}
        self._data = data
        if not self._data.get("frameworks"):
            self.migrate_8screen()

    # ---------- 基础 ----------
    @property
    def size(self) -> int:
        return len([f for f in self._data["frameworks"] if not f.get("archived")])

    def get(self, fid: str) -> dict | None:
        for f in self._data["frameworks"]:
            if f["id"] == fid:
                return f
        return None

    def add(self, framework: dict) -> None:
        if self.get(framework["id"]) is not None:
            raise ValueError(f"框架已存在: {framework['id']}")
        framework.setdefault("score", {"wins": 0, "losses": 0, "win_rate": 0.0})
        s = framework["score"]
        total = s.get("wins", 0) + s.get("losses", 0)
        if not s.get("win_rate") and total:
            s["win_rate"] = round(s.get("wins", 0) / total, 4)
        framework.setdefault("archived", False)
        framework.setdefault("created", datetime.now(timezone.utc).isoformat())
        self._data["frameworks"].append(framework)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    # ---------- 迁入 ----------
    def migrate_8screen(self) -> None:
        """把 storyboard 的 8 屏结构迁入为第一个框架（幂等）。"""
        if self.get(EIGHT_SCREEN_ID) is not None:
            return
        self._data["frameworks"].append({
            "id": EIGHT_SCREEN_ID,
            "type": "详情页",
            "name": "8屏视觉逼单",
            "structure": [
                {"no": s["no"], "name": s["name"], "user_question": s["user_question"],
                 "task": s["task"], "evidence": s["evidence"], "composition": s["composition"]}
                for s in storyboard.EIGHT_SCREENS
            ],
            "screen7_map": storyboard.SCREEN7_BY_CATEGORY,
            "applies_to": {"品类": "常规消费品", "屏数": "6-10屏场景"},
            "score": {"wins": 0, "losses": 0, "win_rate": 0.0},
            "source": "飞书方法论文档",
            "archived": False,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    # ---------- 选择 ----------
    def select(self, framework_type: str | None = None,
               scenario: dict | None = None, include_archived: bool = False) -> list[dict]:
        """按类型/场景筛选，胜率降序。"""
        picked = []
        for f in self._data["frameworks"]:
            if f.get("archived") and not include_archived:
                continue
            if framework_type and f.get("type") != framework_type:
                continue
            if scenario:
                applies = f.get("applies_to", {})
                if not any(str(applies.get(k, "")) == str(v) for k, v in scenario.items()):
                    continue
            picked.append(f)
        picked.sort(key=lambda x: x.get("score", {}).get("win_rate", 0), reverse=True)
        return picked

    # ---------- L11 回流（红线2：唯一 score 修改入口） ----------
    def update_score(self, fid: str, win: bool) -> None:
        f = self.get(fid)
        if f is None:
            raise KeyError(f"框架不存在: {fid}")
        s = f["score"]
        s["wins" if win else "losses"] = s.get("wins" if win else "losses", 0) + 1
        total = s["wins"] + s["losses"]
        s["win_rate"] = round(s["wins"] / total, 4) if total else 0.0
        s["updated"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def retire_if_stale(self, min_samples: int = 10) -> list[str]:
        """胜率 < RETIRE_WIN_RATE 且样本足够 → archived。返回被淘汰 id。"""
        retired = []
        for f in self._data["frameworks"]:
            s = f.get("score", {})
            total = s.get("wins", 0) + s.get("losses", 0)
            if (not f.get("archived") and total >= min_samples
                    and s.get("win_rate", 1.0) < RETIRE_WIN_RATE):
                f["archived"] = True
                f["retired"] = datetime.now(timezone.utc).isoformat()
                retired.append(f["id"])
        if retired:
            self.save()
        return retired


DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "frameworks.json"


def default_library() -> FrameworkLibrary:
    return FrameworkLibrary(DEFAULT_PATH)
