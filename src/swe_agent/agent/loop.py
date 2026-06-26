"""ReAct 主循环 —— 整个 agent 的心脏。

【ReAct 循环一句话】
  while not done and step < max:
      response = LLM(history, tools)        # 1. 模型思考 + 决定动作
      if not response.tool_calls: break     # 2. 模型不再调工具 => 任务完成
      for call in response.tool_calls:      # 3. 执行每个工具调用
          result = tools.execute(call)
          history.append(observe(result))   # 4. 把结果喂回去, 进入下一轮

  整个核心就这 4 步, 下面用 ~60 行可读代码实现。

【可观测性】
  loop 不直接 print, 而是回调 callback(event)。
  CLI 传入彩色打印的 callback; 测试传入记录用的 callback。
  这样 loop 本身纯粹、可测, 展示逻辑和业务逻辑分离。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from swe_agent.llm.base import LLM, LLMResponse, Message, ToolCall
from swe_agent.tools.registry import ToolRegistry
from swe_agent.agent.messages import MessageHistory
from swe_agent.agent.prompts import build_system_prompt


# ── 事件: loop 向外汇报进展的统一格式 ──────────────────────────


@dataclass
class AgentEvent:
    """一次循环中发生的"事件", 供 callback 消费。"""

    kind: str  # "think" | "tool_call" | "tool_result" | "done" | "error" | "step_limit"
    step: int
    # 各 kind 对应字段:
    content: str | None = None        # think/done: 模型的文字
    tool_call: ToolCall | None = None  # tool_call: 本次调用
    tool_output: str | None = None     # tool_result: 工具返回文本
    error: str | None = None          # error: 错误信息
    usage: dict = field(default_factory=dict)  # token 用量


# callback 签名: 收到一个 AgentEvent
Callback = Callable[[AgentEvent], None]


def _noop(_: AgentEvent) -> None:
    """默认 callback: 什么都不做。"""


@dataclass
class AgentRunResult:
    """一次 run 的最终结果。"""

    finished: bool  # 是否正常完成 (而非撞到步数上限)
    final_text: str  # 最后一次文字回复
    steps: int  # 实际跑了多少步
    total_tokens: int  # 累计 token (粗估)


class Agent:
    """ReAct agent。把 LLM + 工具集 串成循环。"""

    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        *,
        max_steps: int = 30,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.temperature = temperature
        self._system = system_prompt or build_system_prompt()

    def run(
        self,
        task: str,
        *,
        callback: Callback = _noop,
    ) -> AgentRunResult:
        """对一个任务跑 ReAct 循环, 返回最终结果。

        Args:
            task: 用户的任务描述
            callback: 每步进展的回调 (CLI 用来打印, 测试用来记录)
        """
        history = MessageHistory(system=self._system)
        history.append(Message(role="user", content=task))

        tool_schemas = self.tools.schemas()
        total_tokens = 0
        last_text = ""

        for step in range(1, self.max_steps + 1):
            # ── 1. 让模型思考 + 决定动作 ──────────────────────
            try:
                resp: LLMResponse = self.llm.chat(
                    history.messages,
                    tools=tool_schemas,
                    temperature=self.temperature,
                )
            except Exception as e:  # noqa: BLE001 — LLM 调用失败不能让 agent 崩死
                callback(AgentEvent(kind="error", step=step, error=f"LLM 调用失败: {e}"))
                return AgentRunResult(
                    finished=False, final_text=f"LLM 调用失败: {e}",
                    steps=step - 1, total_tokens=total_tokens,
                )

            total_tokens += resp.usage.get("total", 0)

            # ── 2. 如果模型不调工具 => 它认为任务完成了 ────────
            if not resp.tool_calls:
                last_text = resp.content or ""
                callback(AgentEvent(kind="done", step=step, content=last_text))
                return AgentRunResult(
                    finished=True, final_text=last_text,
                    steps=step, total_tokens=total_tokens,
                )

            # ── 3. 把模型的"思考 + 工具调用"记入历史 ───────────
            # (assistant 这条同时可能有文字思考和 tool_calls)
            history.append(
                Message(
                    role="assistant",
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                )
            )
            if resp.content:
                callback(
                    AgentEvent(kind="think", step=step, content=resp.content)
                )

            # ── 4. 逐个执行工具调用, 结果回填历史 ─────────────
            for call in resp.tool_calls:
                callback(AgentEvent(kind="tool_call", step=step, tool_call=call))
                result = self.tools.execute(call.name, call.arguments)
                text = result.to_llm_text()
                callback(
                    AgentEvent(kind="tool_result", step=step, tool_output=text)
                )
                history.append(
                    Message(
                        role="tool",
                        content=text,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

            # ── 5. 超长则瘦身历史, 防爆 context ───────────────
            history.truncate_if_needed(max_tokens=8000, keep_recent=6)

        # ── 跑满步数仍未完成 ─────────────────────────────────
        callback(AgentEvent(kind="step_limit", step=self.max_steps))
        return AgentRunResult(
            finished=False,
            final_text=last_text or "(达到步数上限, 未给出最终回复)",
            steps=self.max_steps,
            total_tokens=total_tokens,
        )
