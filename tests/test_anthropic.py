"""Anthropic provider 翻译测试。

【测试策略】
  沙箱没装 anthropic 包, 但翻译逻辑 (staticmethod) 不依赖 SDK 实例。
  我们用 sys.modules 注入一个假的 anthropic 模块, 让 import 通过,
  然后只测纯翻译函数 —— 这恰好是 provider 最易错的地方。

  这一阶段的核心目的: 证明"换 provider 不动 Agent Loop"。
  这里只验证翻译正确性; 真实调用需装 anthropic + 配 key。
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

# ── 注入假的 anthropic 模块, 让 import 通过 (不调真实 SDK) ──────
if "anthropic" not in sys.modules:
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kw: None  # 构造返回 None, 测试不实例化用不到
    sys.modules["anthropic"] = fake

from swe_agent.llm.anthropic_provider import AnthropicProvider  # noqa: E402
from swe_agent.llm.base import Message, ToolCall, ToolSchema  # noqa: E402

# 取静态翻译方法, 绕过实例化
to_cm = AnthropicProvider._to_claude_messages
split_sys = AnthropicProvider._split_system
to_ct = AnthropicProvider._to_claude_tool
from_cr = AnthropicProvider._from_claude_resp


# ── system 分离 ────────────────────────────────────────────────


def test_system_split_out():
    msgs = [
        Message(role="system", content="你是助手"),
        Message(role="user", content="hi"),
    ]
    sys_text, rest = split_sys(msgs)
    assert sys_text == "你是助手"
    assert len(rest) == 1 and rest[0].role == "user"


def test_multiple_system_merged():
    msgs = [
        Message(role="system", content="A"),
        Message(role="system", content="B"),
        Message(role="user", content="hi"),
    ]
    sys_text, rest = split_sys(msgs)
    assert sys_text == "A\n\nB"


# ── user / assistant 翻译 ─────────────────────────────────────


def test_user_message_translation():
    out = to_cm([Message(role="user", content="hello")])
    assert out == [{"role": "user", "content": "hello"}]


def test_assistant_text_only():
    out = to_cm([Message(role="assistant", content="hi there")])
    assert out == [{"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}]


# ── assistant 工具调用 -> tool_use block ───────────────────────


def test_assistant_tool_call_translation():
    out = to_cm(
        [
            Message(
                role="assistant",
                content="我读一下",
                tool_calls=[ToolCall(name="read_file", arguments={"path": "a"}, id="t1")],
            )
        ]
    )
    blocks = out[0]["content"]
    assert out[0]["role"] == "assistant"
    # 第一块是文本
    assert blocks[0] == {"type": "text", "text": "我读一下"}
    # 第二块是 tool_use, input 是 dict (不像 OpenAI 要 JSON 字符串)
    assert blocks[1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "read_file",
        "input": {"path": "a"},
    }


# ── 工具结果 -> user 消息里的 tool_result block ────────────────


def test_tool_result_wrapped_in_user():
    """role=tool 必须包成 user 的 tool_result block (Claude 的硬性要求)。"""
    out = to_cm(
        [Message(role="tool", content="文件内容", tool_call_id="t1", name="read_file")]
    )
    assert out[0]["role"] == "user"
    assert out[0]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "文件内容"}
    ]


def test_multiple_tool_results_merged_into_one_user():
    """连续多个工具结果应合并进同一条 user 消息 (Claude 要求 role 交替)。"""
    out = to_cm(
        [
            Message(role="tool", content="r1", tool_call_id="t1"),
            Message(role="tool", content="r2", tool_call_id="t2"),
        ]
    )
    assert len(out) == 1  # 合并成一条 user
    assert len(out[0]["content"]) == 2
    assert out[0]["content"][0]["tool_use_id"] == "t1"
    assert out[0]["content"][1]["tool_use_id"] == "t2"


# ── ToolSchema -> Claude tool (input_schema) ──────────────────


def test_tool_schema_uses_input_schema():
    sch = ToolSchema(
        name="x", description="d", parameters={"type": "object", "properties": {}}
    )
    t = to_ct(sch)
    assert t["name"] == "x"
    assert t["description"] == "d"
    # 关键: Claude 用 input_schema, 不是 parameters
    assert t["input_schema"] == {"type": "object", "properties": {}}


# ── Claude response -> 统一 LLMResponse ───────────────────────


def _block(typ, **kw):
    return SimpleNamespace(type=typ, **kw)


def test_response_text_and_tool_use():
    """Claude 返回多个 content block (文本 + 工具调用), 都要正确提取。"""
    resp = SimpleNamespace(
        content=[
            _block("text", text="我想读文件"),
            _block("tool_use", id="t9", name="read_file", input={"path": "a.py"}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=50, output_tokens=10),
    )
    r = from_cr(resp)
    assert r.content == "我想读文件"
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "read_file"
    assert r.tool_calls[0].arguments == {"path": "a.py"}  # 直接 dict, 无需反序列化
    assert r.tool_calls[0].id == "t9"
    assert r.stop_reason == "tool_use"
    assert r.usage == {"prompt": 50, "completion": 10, "total": 60}


def test_response_text_only():
    resp = SimpleNamespace(
        content=[_block("text", text="done")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    r = from_cr(resp)
    assert r.content == "done"
    assert r.tool_calls == []
    assert r.usage["total"] == 8


def test_response_missing_usage_safe():
    resp = SimpleNamespace(
        content=[_block("text", text="x")],
        stop_reason="end_turn",
        usage=None,
    )
    r = from_cr(resp)
    assert r.usage == {}


# ── 关键: 与 OpenAI provider 产出相同的统一协议 ────────────────
# 这是"抽象层正确"的最终证明: 两家 provider 翻译出的 LLMResponse 结构一致,
# Agent Loop 因此无需感知差异。


def test_unified_protocol_consistency():
    """Claude 的 tool_use block 翻译出的 ToolCall,
    和 OpenAI 的 tool_calls 翻译出的 ToolCall 是同一种结构。"""
    from swe_agent.llm.openai_provider import OpenAIProvider

    # Claude 侧
    claude_resp = SimpleNamespace(
        content=[_block("tool_use", id="c1", name="grep", input={"pattern": "foo"})],
        stop_reason="tool_use",
        usage=None,
    )
    cr = from_cr(claude_resp)

    # OpenAI 侧 (同样的语义)
    oi_resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(
                                name="grep", arguments='{"pattern": "foo"}'
                            ),
                        )
                    ],
                ),
            )
        ],
        usage=None,
    )
    oir = OpenAIProvider._from_openai_resp(oi_resp)

    # 两者产出结构一致 —— 这就是 Agent Loop 能无视 provider 差异的基础
    assert cr.tool_calls[0].name == oir.tool_calls[0].name
    assert cr.tool_calls[0].arguments == oir.tool_calls[0].arguments
    assert cr.tool_calls[0].id == oir.tool_calls[0].id
