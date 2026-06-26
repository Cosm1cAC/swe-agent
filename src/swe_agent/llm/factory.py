"""LLM 工厂: 按 Config.provider 生产对应 provider 实例。

这是抽象层的"入口": Agent Loop 和 CLI 永远只调用 make_llm(),
不直接 import 具体的 OpenAIProvider / AnthropicProvider。
这样换 provider 只改配置, 不改任何业务代码。
"""
from __future__ import annotations

from swe_agent.config import Config
from swe_agent.llm.base import LLM
from swe_agent.llm.openai_provider import OpenAIProvider


def make_llm(cfg: Config) -> LLM:
    """根据 cfg.provider 返回对应的 LLM 实例。

    延迟 import anthropic: 它是可选依赖, 只有真用 Claude 时才需要装。
    """
    provider = cfg.provider.lower()

    if provider == "openai":
        return OpenAIProvider(
            model=cfg.openai_model,
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
        )

    if provider == "anthropic":
        # 延迟导入: 没装 anthropic 包时, 只有用 Claude 才会报错, 不影响 OpenAI 用户
        try:
            from swe_agent.llm.anthropic_provider import AnthropicProvider
        except ImportError as e:
            raise ImportError(
                "使用 Anthropic provider 需要安装 anthropic 包:\n"
                '  pip install -e ".[anthropic]"'
            ) from e
        return AnthropicProvider(
            model=cfg.anthropic_model,
            api_key=cfg.anthropic_api_key,
        )

    raise ValueError(
        f"未知 provider: {cfg.provider!r} (应为 'openai' 或 'anthropic')"
    )
