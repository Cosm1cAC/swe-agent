"""LLM 抽象层测试 —— 不联网, 只测协议翻译逻辑。

provider 最容易出错的地方就是双向翻译, 这里把它锁死。
"""
from __future__ import annotations

from types import SimpleNamespace

from swe_agent.llm.base import Message, ToolCall, ToolSchema
from swe_agent.llm.openai_provider import OpenAIProvider

to_oi = OpenAIProvider._to_openai_msg


# ── 统一 Message -> OpenAI message ──────────────────────────────


def test_system_message_translation():
    m = to_oi(Message(role="system", content="你是助手"))
    assert m == {"role": "system", "content": "你是助手"}


def test_user_message_translation():
    m = to_oi(Message(role="user", content="hello"))
    assert m == {"role": "user", "content": "hello"}


def test_tool_result_translation():
    """role=tool 必须带 tool_call_id + content。"""
    m = to_oi(
        Message(role="tool", content="结果", tool_call_id="call_1", name="read_file")
    )
    assert m == {"role": "tool", "content": "结果", "tool_call_id": "call_1"}


def test_assistant_with_tool_calls_translation():
    """assistant 的 tool_calls 参数要序列化成 JSON 字符串。"""
    m = to_oi(
        Message(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(name="read_file", arguments={"path": "a.py"}, id="c1")],
        )
    )
    assert m["role"] == "assistant"
    assert m["tool_calls"][0]["id"] == "c1"
    assert m["tool_calls"][0]["function"]["name"] == "read_file"
    # 关键: arguments 是 JSON 字符串
    assert m["tool_calls"][0]["function"]["arguments"] == '{"path": "a.py"}'


# ── ToolSchema -> OpenAI tool ───────────────────────────────────


def test_tool_schema_translation():
    sch = ToolSchema(
        name="read_file",
        description="读文件",
        parameters={"type": "object", "properties": {}},
    )
    t = OpenAIProvider._to_openai_tool(sch)
    assert t["type"] == "function"
    assert t["function"]["name"] == "read_file"
    assert t["function"]["description"] == "读文件"


# ── OpenAI response -> 统一 LLMResponse ────────────────────────


def _fake_resp(content=None, tool_calls=None, finish="stop", with_usage=True):
    tc_objs = None
    if tool_calls:
        tc_objs = [
            SimpleNamespace(id=tid, function=SimpleNamespace(name=name, arguments=args))
            for tid, name, args in tool_calls
        ]
    usage = (
        SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        if with_usage
        else None
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish,
                message=SimpleNamespace(content=content, tool_calls=tc_objs),
            )
        ],
        usage=usage,
    )


def test_response_plain_text():
    r = OpenAIProvider._from_openai_resp(
        _fake_resp(content="你好", finish="stop", tool_calls=None)
    )
    assert r.content == "你好"
    assert r.tool_calls == []
    assert r.stop_reason == "stop"


def test_response_tool_calls_parsed():
    """tool_calls 的 arguments JSON 字符串要解析成 dict。"""
    r = OpenAIProvider._from_openai_resp(
        _fake_resp(
            content=None,
            finish="tool_calls",
            tool_calls=[("c1", "write_file", '{"path": "x.py", "content": "1"}')],
        )
    )
    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    assert tc.id == "c1"
    assert tc.name == "write_file"
    assert tc.arguments == {"path": "x.py", "content": "1"}


def test_response_malformed_json_falls_back_to_empty():
    """非法 JSON 参数必须兜底成 {}, 不能让循环崩。"""
    r = OpenAIProvider._from_openai_resp(
        _fake_resp(
            content=None,
            finish="tool_calls",
            tool_calls=[("c2", "grep", "{bad json")],
        )
    )
    assert r.tool_calls[0].arguments == {}


def test_response_usage_extracted():
    r = OpenAIProvider._from_openai_resp(_fake_resp(content="hi"))
    assert r.usage == {"prompt": 10, "completion": 5, "total": 15}


def test_response_missing_usage_safe():
    """usage 字段缺失时不能报错。"""
    r = OpenAIProvider._from_openai_resp(_fake_resp(content="hi", with_usage=False))
    assert r.usage == {}
