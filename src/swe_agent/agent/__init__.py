"""Agent 核心: ReAct 主循环、消息历史、系统提示词。

对外提供:
  - Agent          ReAct agent (主入口)
  - AgentRunResult 一次 run 的结果
  - AgentEvent / Callback  可观测性事件
"""
from swe_agent.agent.loop import (
    Agent,
    AgentEvent,
    AgentRunResult,
    Callback,
)

__all__ = ["Agent", "AgentEvent", "AgentRunResult", "Callback"]
