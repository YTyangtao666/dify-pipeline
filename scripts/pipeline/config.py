"""配置：从环境变量读取（兼容 .env），提供输出目录派生。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    base_url: str
    api_key: str
    image_model: str
    vlm_model: str
    llm_model: str
    proxy: str | None = None
    out_dir: Path = field(default_factory=lambda: Path("output"))
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    # VLM 兜底端点（主端点 403 配额耗尽时切换，如智谱 glm-4v-flash 免费）
    vlm_fallback_url: str | None = None
    vlm_fallback_key: str | None = None
    vlm_fallback_model: str | None = None
    vlm_fallback_proxy: str | None = None
    eval_votes: int = 1  # VLM 判定投票数（>1 启用多数决，抗概率性输出）

    @property
    def images_dir(self) -> Path:
        return self.out_dir / "images"

    @property
    def eval_dir(self) -> Path:
        return self.out_dir / "eval"

    @property
    def videos_dir(self) -> Path:
        return self.out_dir / "videos"

    @property
    def products_file(self) -> Path:
        return Path("data/products.json")

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.environ.get("ARK_API_KEY")
        if not api_key:
            raise RuntimeError("ARK_API_KEY 未设置：请在 .env 或环境变量中提供中转站 key")
        out_dir = Path(os.environ.get("OUT_DIR", "output"))
        return cls(
            base_url=os.environ.get("ARK_BASE_URL", "https://yunwu.ai/v1"),
            api_key=api_key,
            image_model=os.environ.get("IMAGE_MODEL", "qwen-image-2.0-2026-03-03"),
            vlm_model=os.environ.get("VLM_MODEL", "gemini-3.5-flash"),
            llm_model=os.environ.get("LLM_MODEL", "deepseek-v3.2"),
            proxy=os.environ.get("ARK_PROXY") or None,
            tts_voice=os.environ.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
            out_dir=out_dir,
            vlm_fallback_url=os.environ.get("VLM_FALLBACK_URL") or None,
            vlm_fallback_key=os.environ.get("VLM_FALLBACK_KEY") or None,
            vlm_fallback_model=os.environ.get("VLM_FALLBACK_MODEL") or None,
            vlm_fallback_proxy=os.environ.get("VLM_FALLBACK_PROXY") or None,
            eval_votes=int(os.environ.get("EVAL_VOTES", "1") or 1),
        )
