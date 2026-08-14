"""pipeline.config 模块测试：环境变量读取与默认值"""
import os


def test_config_reads_mandatory_vars(monkeypatch):
    monkeypatch.setenv("ARK_BASE_URL", "https://yunwu.ai/v1")
    monkeypatch.setenv("ARK_API_KEY", "sk-test123")
    monkeypatch.setenv("IMAGE_MODEL", "qwen-image-2.0")
    monkeypatch.setenv("VLM_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v3.2")
    monkeypatch.setenv("ARK_PROXY", "")  # 空串视为无代理

    from scripts.pipeline.config import Config

    cfg = Config.from_env()
    assert cfg.base_url == "https://yunwu.ai/v1"
    assert cfg.api_key == "sk-test123"
    assert cfg.image_model == "qwen-image-2.0"
    assert cfg.vlm_model == "gemini-3.5-flash"
    assert cfg.llm_model == "deepseek-v3.2"
    assert cfg.proxy is None


def test_config_proxy_and_output_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("ARK_BASE_URL", "https://x/v1")
    monkeypatch.setenv("ARK_API_KEY", "sk-x")
    monkeypatch.setenv("ARK_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("OUT_DIR", str(tmp_path))

    from scripts.pipeline.config import Config

    cfg = Config.from_env()
    assert cfg.proxy == "http://127.0.0.1:7897"
    # 输出目录在 out_dir 下派生
    assert str(cfg.images_dir).startswith(str(tmp_path))
    assert str(cfg.eval_dir).startswith(str(tmp_path))
    assert str(cfg.videos_dir).startswith(str(tmp_path))
    # products_file 固定为 data/products.json（不在 out_dir 下）


def test_config_missing_api_key_raises(monkeypatch):
    monkeypatch.setenv("ARK_BASE_URL", "https://x/v1")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    from scripts.pipeline.config import Config

    import pytest
    with pytest.raises(RuntimeError, match="ARK_API_KEY"):
        Config.from_env()
