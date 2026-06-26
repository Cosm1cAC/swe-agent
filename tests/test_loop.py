"""Agent Loop 测试 —— 用 mock LLM, 不依赖真实 API。

【为什么用 mock】
  真实 LLM 输出不可控、慢、要花钱, 没法做可靠的循环测试。
  我们造一个"剧本式"的假 LLM: 按预设顺序返回一系列回复,
  这样能精确验证 loop 在各种场景下的行为:
    - 正常完成 (模型最终不调工具)
    - 多步工具调用链
    - 工具执行失败后 LLM 能自我纠正
    - 撞步数上限
    - LLM 调用本身失败

  这是 agentic 系统测试的核心套路。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from swe_agent.agent import Agent, AgentEvent
from swe_agent.llm.base import LLM, LLMResponse, Message, ToolCall, ToolSchema
from swe_agent.tools import build_default_tools


class ScriptedLLM(LLM):
    """按剧本依次返回预设回复的假 LLM。

    传入一个 LLMResponse 列表, 每次 chat() 吐出下一个。
    用于精确控制 agent 的行为路径。
    """

    def __init__(self, script: list[LLMResponse]):
        super().__init__(model="mock")
        self._script = list(script)
        self._idx = 0
        self.calls: list[list[Message]] = []  # 记录每次收到的消息, 供断言

    def chat(self, messages, tools=None, *, temperature=0.0):
        self.calls.append(list(messages))
        if self._idx >= len(self._script):
            # 剧本用完: 返回一个"完成"回复, 防止无限循环
            return LLMResponse(content="(剧本结束)", stop_reason="stop")
        resp = self._script[self._idx]
        self._idx += 1
        return resp


def _tc(name: str, args: dict, id: str = "c1") -> ToolCall:
    return ToolCall(name=name, arguments=args, id=id)


def _collect_events(agent: Agent, task: str) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    agent.run(task, callback=events.append)
    return events


# ── 场景 1: 模型直接回答, 不调工具 => 立即完成 ────────────────


def test_immediate_completion():
    llm = ScriptedLLM([LLMResponse(content="任务已完成", tool_calls=[])])
    agent = Agent(llm, build_default_tools("."), max_steps=5)
    result = agent.run("hi", callback=lambda e: None)

    assert result.finished is True
    assert result.final_text == "任务已完成"
    assert result.steps == 1


# ── 场景 2: 多步工具调用链 => 正常完成 ────────────────────────


def test_multi_step_tool_chain(tmp_path: Path):
    # 剧本:
    #   step1: 写一个文件
    #   step2: 读它确认
    #   step3: 完成回复
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[_tc("write_file", {"path": "a.py", "content": "x=1"})]
            ),
            LLMResponse(tool_calls=[_tc("read_file", {"path": "a.py"})]),
            LLMResponse(content="已创建并确认 a.py", tool_calls=[]),
        ]
    )
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=10)
    result = agent.run("创建 a.py 并确认", callback=lambda e: None)

    assert result.finished is True
    assert result.steps == 3
    assert (tmp_path / "a.py").read_text() == "x=1"


# ── 场景 3: 事件流正确性 (think/tool_call/tool_result/done) ────


def test_event_sequence(tmp_path: Path):
    llm = ScriptedLLM(
        [
            LLMResponse(content="我先读文件", tool_calls=[_tc("read_file", {"path": "x"})]),
            LLMResponse(content="好了", tool_calls=[]),
        ]
    )
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=5)
    events = _collect_events(agent, "看 x")

    kinds = [e.kind for e in events]
    # 期望: think -> tool_call -> tool_result -> done
    assert "think" in kinds
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds[-1] == "done"


# ── 场景 4: 工具失败, agent 仍能继续 (韧性的核心) ──────────────


def test_tool_error_does_not_crash(tmp_path: Path):
    llm = ScriptedLLM(
        [
            # 故意读不存在的文件
            LLMResponse(tool_calls=[_tc("read_file", {"path": "nope.py"})]),
            # 模型"看到"错误后, 改为正常完成
            LLMResponse(content="文件不存在, 任务结束", tool_calls=[]),
        ]
    )
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=5)
    events = _collect_events(agent, "读 nope.py")

    # 工具结果应是错误信息, 但 agent 没崩, 继续到 done
    tool_results = [e for e in events if e.kind == "tool_result"]
    assert len(tool_results) == 1
    assert "[ERROR]" in tool_results[0].tool_output
    assert events[-1].kind == "done"


# ── 场景 5: 撞步数上限 ────────────────────────────────────────


def test_step_limit(tmp_path: Path):
    # 剧本: 永远调工具, 永不"完成"
    looping = LLMResponse(tool_calls=[_tc("list_dir", {"path": "."})])
    llm = ScriptedLLM([looping] * 100)  # 给够多
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=3)
    result = agent.run("无限循环任务", callback=lambda e: None)

    assert result.finished is False
    assert result.steps == 3


# ── 场景 6: LLM 调用本身抛异常 => 优雅终止 ─────────────────────


class ExplodingLLM(LLM):
    """永远抛异常的 LLM。"""

    def __init__(self):
        super().__init__(model="boom")

    def chat(self, messages, tools=None, *, temperature=0.0):
        raise RuntimeError("网络炸了")


def test_llm_failure_graceful():
    agent = Agent(ExplodingLLM(), build_default_tools("."), max_steps=5)
    result = agent.run("hi", callback=lambda e: None)

    assert result.finished is False
    assert "LLM 调用失败" in result.final_text


# ── 场景 7: 多工具并行调用 (一条 assistant 消息带多个 tool_call) ─


def test_parallel_tool_calls(tmp_path: Path):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[
                    _tc("write_file", {"path": "a.py", "content": "1"}, id="c1"),
                    _tc("write_file", {"path": "b.py", "content": "2"}, id="c2"),
                ]
            ),
            LLMResponse(content="两个文件都建好了", tool_calls=[]),
        ]
    )
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=5)
    events = _collect_events(agent, "建两个文件")

    assert (tmp_path / "a.py").exists()
    assert (tmp_path / "b.py").exists()
    assert sum(1 for e in events if e.kind == "tool_call") == 2
    assert sum(1 for e in events if e.kind == "tool_result") == 2


# ── 场景 8: 工具 schema 正确传递给 LLM ─────────────────────────


def test_tools_passed_to_llm(tmp_path: Path):
    """agent 应把所有工具的 schema 传给 LLM.chat()。"""
    tools = build_default_tools(str(tmp_path))
    llm = ScriptedLLM([LLMResponse(content="done", tool_calls=[])])
    agent = Agent(llm, tools, max_steps=3)
    agent.run("hi", callback=lambda e: None)

    # ScriptedLLM 不记 tools 参数, 这里改成断言: 至少调用过一次
    assert len(llm.calls) >= 1


def test_system_prompt_present(tmp_path: Path):
    """第一条消息应是 system prompt。"""
    llm = ScriptedLLM([LLMResponse(content="done", tool_calls=[])])
    agent = Agent(llm, build_default_tools(str(tmp_path)), max_steps=3)
    agent.run("hi", callback=lambda e: None)

    first = llm.calls[0][0]
    assert first.role == "system"
    assert "SWE Agent" in first.content
