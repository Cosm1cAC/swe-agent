"""OpenAI 兼容 provider。

覆盖范围: OpenAI 官方 / DeepSeek / 通义 Qwen / Groq / 智谱 / 月之暗面 / 本地 vLLM 等
—— 只要接口是 OpenAI Chat Completions + tool_calls 协议, 都能用这一个 provider。

切换厂商只需改 Config 里的 base_url + model + api_key (见 .env.example)。

【翻译要点】
  统一协议              ->  OpenAI 格式
  ────────────────────────────────────────
  Message(role, content) -> {"role", "content"}
  Message(role=assistant, tool_calls) -> {"role":"assistant", "content", "tool_calls":[...]}
  Message(role=tool, content, tool_call_id) -> {"role":"tool", "tool_call_id", "content"}
  ToolSchema             -> {"type":"function", "function":{name, description, parameters}}
  返回的 tool_calls      -> 解析 JSON 字符串成 dict, 包成统一 ToolCall
"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from swe_agent.llm.base import LLM, LLMResponse, Message, ToolCall, ToolSchema


class OpenAIProvider(LLM):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
    ):
        super().__init__(model)
        # OpenAI SDK 的客户端; base_url 决定了实际打到哪家服务
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    # ── 公开接口 ───────────────────────────────────────────────
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        temperature: float = 0.0,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_openai_msg(m) for m in messages],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [self._to_openai_tool(t) for t in tools]

        resp = self._client.chat.completions.create(**kwargs)
        return self._from_openai_resp(resp)

    # ── 翻译: 统一 Message -> OpenAI message ────────────────────
    @staticmethod
    def _to_openai_msg(m: Message) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": m.role}

        if m.role == "tool":
            # 工具结果: OpenAI 要 tool_call_id + content
            msg["content"] = m.content or ""
            msg["tool_call_id"] = m.tool_call_id
            return msg

        if m.content is not None:
            msg["content"] = m.content

        if m.tool_calls:
            # assistant 发起的工具调用
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # 参数序列化成 JSON 字符串 (OpenAI 要求字符串)
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ]
        return msg

    # ── 翻译: 统一 ToolSchema -> OpenAI tool ────────────────────
    @staticmethod
    def _to_openai_tool(t: ToolSchema) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }

    # ── 翻译: OpenAI response -> 统一 LLMResponse ───────────────
    @staticmethod
    def _from_openai_resp(resp: Any) -> LLMResponse:
        choice = resp.choices[0]
        am = choice.message  # assistant message

        tool_calls: list[ToolCall] = []
        for tc in (am.tool_calls or []):
            # OpenAI 把参数当 JSON 字符串传, 这里解析回 dict
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                # 模型偶尔吐出非法 JSON, 兜底成空 dict, 别让整个循环崩
                args = {}
            tool_calls.append(ToolCall(name=tc.function.name, arguments=args, id=tc.id))

        usage = {}
        if getattr(resp, "usage", None):
            usage = {
                "prompt": resp.usage.prompt_tokens,
                "completion": resp.usage.completion_tokens,
                "total": resp.usage.total_tokens,
            }

        return LLMResponse(
            content=am.content,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            usage=usage,
        )
