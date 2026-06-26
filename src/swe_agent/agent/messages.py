"""对话历史管理: 维护消息列表 + token 估算 + 超长截断。

【为什么需要这个模块】
  agent 干活会产生大量消息 (每步 think/act/observe 都是几条),
  长任务下很容易超过模型的 context 上限。
  所以需要一个能"记账" (算 token) 和"瘦身" (截断旧消息) 的管理器。

【token 估算】
  精确计数需要 tokenizer (如 tiktoken), 但那是个额外依赖,
  且不同模型 tokenizer 不同。这里用一个简单且够用的经验近似:
  中文 ~1.5 字符/token, 英文 ~4 字符/token, 取个折中 —— 字符数 / 3.5。
  只用于"该不该截断"的判断, 不用于计费。
"""
from __future__ import annotations

from swe_agent.llm.base import Message


class MessageHistory:
    """对话历史。封装增删查 + token 估算/截断。"""

    def __init__(self, system: str | None = None):
        self._msgs: list[Message] = []
        if system:
            self._msgs.append(Message(role="system", content=system))

    @property
    def messages(self) -> list[Message]:
        return self._msgs

    def append(self, m: Message) -> None:
        self._msgs.append(m)

    def extend(self, msgs: list[Message]) -> None:
        self._msgs.extend(msgs)

    def __len__(self) -> int:
        return len(self._msgs)

    # ── token 估算 ─────────────────────────────────────────────

    @staticmethod
    def estimate_tokens(m: Message) -> int:
        """粗估一条消息的 token 数。"""
        total_chars = 0
        if m.content:
            total_chars += len(m.content)
        for tc in m.tool_calls:
            total_chars += len(tc.name)
            total_chars += len(str(tc.arguments))
        # 粗略近似: 每 ~3.5 字符约 1 token, 最低算 1
        return max(1, total_chars // 4)

    def total_tokens(self) -> int:
        return sum(self.estimate_tokens(m) for m in self._msgs)

    # ── 截断 ───────────────────────────────────────────────────

    def truncate_if_needed(self, max_tokens: int, keep_recent: int = 6) -> bool:
        """如果总 token 超过上限, 删掉中间较老的消息, 保留:
          - system 消息 (始终保留, 在最前)
          - 最近 keep_recent 条消息 (含最新一轮, 在最后)

        返回是否发生了截断。

        注意: 这是一个"足够简单可用"的策略;
              高级做法是对被删内容做摘要压缩, 这里留给后续迭代。
        """
        if self.total_tokens() <= max_tokens:
            return False

        # 分出 system 头部 + 其余
        system_msgs: list[Message] = []
        rest: list[Message] = []
        for m in self._msgs:
            (system_msgs if m.role == "system" else rest).append(m)

        # 只在 rest 足够长时才有意义截断
        if len(rest) <= keep_recent:
            return False

        kept_tail = rest[-keep_recent:]
        # 安全: 截断后如果开头是 role=tool (工具结果), 它会"悬空"
        # (没有对应的 tool_call), 多数 API 会报错。这里丢掉悬空的 tool 头部。
        while kept_tail and kept_tail[0].role == "tool":
            kept_tail.pop(0)

        self._msgs = system_msgs + kept_tail
        return True
