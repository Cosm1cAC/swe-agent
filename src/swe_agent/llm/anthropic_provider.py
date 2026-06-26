"""Anthropic Claude provider。

【这一阶段的核心意义】
  不是为了"多一个模型", 而是为了证明阶段 1 的抽象层设计正确:
    - 加 Claude 只写这一个文件
    - Agent Loop 一行不改
    - 切换只改 .env 的 LLM_PROVIDER=anthropic
  如果做到, 就说明抽象成功了。

【Claude 与 OpenAI 的关键差异 (翻译难点)】
  Claude 的消息不是 {role, content:str} 这么简单, 而是:
    content 是一个"block 列表", 每个块有 type:
      - {type:"text", text:"..."}          文本
      - {type:"tool_use", id, name, input} 工具调用
      - {type:"tool_result", tool_use_id, content} 工具结果
  而且 Claude 的角色只有 user/assistant, 工具结果要塞进 user 消息里。
  system 是顶级参数, 不在 messages 列表里。

  我们在内部把这些差异全部吸收, 对外仍是统一的 Message / LLMResponse。
"""
from __future__ import annotations

from typing import Any

from anthropic import Anthropic

from swe_agent.llm.base import LLM, LLMResponse, Message, ToolCall, ToolSchema


class AnthropicProvider(LLM):
    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        self._client = Anthropic(api_key=api_key)

    # ── 公开接口 ───────────────────────────────────────────────
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # 1) 分离 system (Claude 要它作顶级参数)
        system_text, convo = self._split_system(messages)

        # 2) 把统一消息翻译成 Claude 的 block 格式
        claude_msgs = self._to_claude_messages(convo)

        # 3) 翻译工具 schema (Claude 用 input_schema 而非 parameters)
        claude_tools = [self._to_claude_tool(t) for t in tools] if tools else None

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_msgs,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if claude_tools:
            kwargs["tools"] = claude_tools

        resp = self._client.messages.create(**kwargs)
        return self._from_claude_resp(resp)

    # ── 翻译: 统一 Message 列表 -> Claude messages ─────────────

    @staticmethod
    def _split_system(messages: list[Message]) -> tuple[str, list[Message]]:
        """把 system 消息抽出来 (Claude 要它做顶级参数)。"""
        sys_parts = [m.content for m in messages if m.role == "system" and m.content]
        rest = [m for m in messages if m.role != "system"]
        return "\n\n".join(sys_parts), rest

    @staticmethod
    def _to_claude_messages(msgs: list[Message]) -> list[dict[str, Any]]:
        """统一 Message -> Claude 的 content-blocks 格式。

        关键: Claude 的工具结果 (role=tool) 必须包在 user 消息的
              tool_result block 里, 不能单独成条。
        """
        out: list[dict[str, Any]] = []
        for m in msgs:
            if m.role == "tool":
                # 工具结果 -> user 消息里的 tool_result block
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content or "",
                }
                # 若上一条已是 user(工具结果聚合), 合并进去; 否则新建
                if out and out[-1]["role"] == "user" and _is_tool_result_user(out[-1]):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == "assistant":
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,  # Claude 直接要 dict, 不需 JSON 字符串
                        }
                    )
                out.append({"role": "assistant", "content": content})
            else:  # user
                out.append({"role": "user", "content": m.content or ""})
        return out

    # ── 翻译: ToolSchema -> Claude tool ────────────────────────
    @staticmethod
    def _to_claude_tool(t: ToolSchema) -> dict[str, Any]:
        # Claude 用 input_schema (语义等同 OpenAI 的 parameters)
        return {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }

    # ── 翻译: Claude response -> 统一 LLMResponse ──────────────
    @staticmethod
    def _from_claude_resp(resp: Any) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=block.name,
                        arguments=block.input or {},
                        id=block.id,
                    )
                )

        usage = {}
        if getattr(resp, "usage", None):
            u = resp.usage
            inp = getattr(u, "input_tokens", 0)
            out = getattr(u, "output_tokens", 0)
            usage = {"prompt": inp, "completion": out, "total": inp + out}

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=getattr(resp, "stop_reason", None),
            usage=usage,
        )


def _is_tool_result_user(msg: dict[str, Any]) -> bool:
    """判断一条 user 消息是否是"工具结果聚合"消息 (content 全是 tool_result block)。"""
    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )
