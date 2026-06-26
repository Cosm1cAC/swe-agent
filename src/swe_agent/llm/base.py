"""LLM 抽象层 —— 统一协议 + 抽象基类。

【为什么需要这层抽象?】
  OpenAI 用 messages=[{role, content, tool_calls}], 工具调用是 tool_calls 字段;
  Anthropic 用 content blocks, 工具调用是 {type: "tool_use"} 的 block;
  它们的 "形状" 完全不同。如果 Agent Loop 直接对接某一家,
  换模型就得改核心循环 —— 这是最糟的耦合。

【这里的做法】
  定义一套 provider 无关的内部数据结构 (Message / ToolCall / ToolResult / LLMResponse),
  + 一个抽象基类 LLM.chat()。
  每个 provider 在内部做 "统一协议 <-> 厂商格式" 的双向翻译。
  Agent Loop 永远只跟这套统一协议打交道。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ────────────────────────────────────────────────────────────────
#  统一数据结构 (provider 无关)
# ────────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """模型发起的一次工具调用。

    无论 OpenAI 还是 Anthropic, 翻译后都归一成这个结构。
    - name:     要调用的工具名 (如 "read_file")
    - arguments: 参数, 已解析为 dict (不再是一坨 JSON 字符串)
    - id:       本次调用的唯一标识, 用来把"工具结果"配对回"这次调用"
    """

    name: str
    arguments: dict[str, Any]
    id: str


@dataclass
class Message:
    """一条对话消息。统一用 role 区分角色, 用 content 存文本。

    content 为 None 表示"无文本"(比如纯工具调用消息)。
    tool_calls 仅在 assistant 发起调用时非空。
    tool_call_id 仅在 role=="tool"(工具返回结果) 时有效, 指向被回应的那次调用。
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # role=="tool" 时, 指向所回应的 ToolCall.id
    name: str | None = None  # role=="tool" 时, 工具名 (部分 API 需要)


@dataclass
class ToolSchema:
    """一个工具的 JSON Schema 描述, 喂给 LLM 让它知道"有哪些工具可用"。

    这是 OpenAI/Anthropic 通用的 function-calling schema 形状,
    各 provider 在翻译时几乎不需要改。
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema, 描述参数结构


@dataclass
class LLMResponse:
    """LLM 一次回复的统一结构。

    - content:    模型输出的文本 (可能是思考过程/给用户的话, 也可能为空)
    - tool_calls: 模型想调用的工具 (空列表 = 模型选择直接回答, 不调工具)
    - stop_reason: 为什么停 (stop / tool_calls / length / ...), 调试用
    - usage:      token 用量 {prompt, completion, total}, 供统计
    """

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


# ────────────────────────────────────────────────────────────────
#  抽象基类
# ────────────────────────────────────────────────────────────────


class LLM(ABC):
    """所有 provider 必须实现的接口。

    子类负责:
      1. 把统一 Message 列表翻译成自家 API 格式
      2. 把工具 schema 翻译成自家格式
      3. 调 API
      4. 把返回结果翻译回统一 LLMResponse

    Agent Loop 只认 chat() 这个签名, 完全不关心底下是哪家。
    """

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """发起一次对话, 返回统一 LLMResponse。

        Args:
            messages: 对话历史 (含 system / user / assistant / tool 各角色)。
            tools:    可用工具的 schema 列表; None 表示本次不允许调工具。
            temperature: 采样温度, agent 场景默认 0 (确定性)。
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model!r})"
