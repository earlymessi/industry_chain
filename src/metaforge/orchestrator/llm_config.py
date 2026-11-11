"""LLM 功能开关（环境变量）。"""

from __future__ import annotations

import os


def llm_enabled() -> bool:
    if os.getenv("LLM_ENABLED") != "1":
        return False
    key = (os.getenv("DEEPSEEK_API_KEY") or os.getenv("ZHIPU_API_KEY") or "").strip()
    return bool(key)


def llm_fallback_rule() -> bool:
    return os.getenv("LLM_FALLBACK", "rule") == "rule"


def llm_provider() -> str:
    if (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return "deepseek"
    if (os.getenv("ZHIPU_API_KEY") or "").strip():
        return "zhipu"
    return ""


def llm_model_name() -> str:
    if llm_provider() == "deepseek":
        return (os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro").strip()
    if llm_provider() == "zhipu":
        return (os.getenv("ZHIPU_MODEL") or "glm-4.5-air").strip()
    return ""


def llm_provider_label_zh() -> str:
    mapping = {"deepseek": "DeepSeek", "zhipu": "智谱"}
    return mapping.get(llm_provider(), "大模型")


def llm_display_label() -> str:
    """界面展示用：提供商 · 模型名。"""
    provider = llm_provider_label_zh()
    model = llm_model_name()
    if model:
        return f"{provider} · {model}"
    return provider or "大模型"
