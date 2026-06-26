"""LLM 抽象层 —— provider 无关的统一接口。

对外提供:
  - LLM (抽象基类)      — 所有 provider 的统一接口
  - Message / ToolCall / ToolSchema / LLMResponse — 统一协议
  - make_llm(config)    — 按 config 生产对应 provider (入口)
"""
from swe_agent.llm.base import LLM, LLMResponse, Message, ToolCall, ToolSchema
from swe_agent.llm.factory import make_llm

__all__ = [
    "LLM",
    "Message",
    "ToolCall",
    "ToolSchema",
    "LLMResponse",
    "make_llm",
]
