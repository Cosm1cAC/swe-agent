"""Shell 执行工具: run_shell。

【为什么需要它】
  agent 要能"跑测试 / 跑构建 / 装依赖", 才能验证自己的改动对不对。
  这是 agentic coding 区别于"纯代码生成"的关键 —— 形成闭环:
    改代码 -> 跑测试 -> 看结果 -> 再改

【安全护栏】
  - 在 workspace 内执行 (cwd 锁定)
  - 超时上限 (防止死循环命令)
  - 输出长度上限 (防止海量日志撑爆 context)
  - 把 stdout/stderr 都返回给 LLM, 让它自己判断成功与否
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from swe_agent.tools.base import Tool, ToolError, ToolResult

_TIMEOUT = 60  # 秒
_MAX_OUTPUT = 8000  # 字符, 超出截断


class RunShellTool(Tool):
    name = "run_shell"
    description = (
        "在 workspace 内执行一条 shell 命令 (如运行测试、构建、git 操作)。"
        "返回 stdout/stderr 和退出码。注意: 命令应有明确结束, 不要交互式。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "timeout": {
                    "type": "integer",
                    "description": f"超时秒数, 默认 {_TIMEOUT}",
                },
            },
            "required": ["command"],
        }

    def run(self, *, command: str, timeout: int | None = None) -> ToolResult:
        cwd = Path(self.workspace).resolve()
        timeout = timeout or _TIMEOUT

        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"命令超时 ({timeout}s): {command}")
        except (OSError, ValueError) as e:
            raise ToolError(f"无法执行命令: {e}")

        out = (proc.stdout or "").rstrip()
        err = (proc.stderr or "").rstrip()
        code = proc.returncode

        # 拼装给 LLM 看的文本: 退出码 + 输出
        parts = [f"[exit code: {code}]"]
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        text = "\n".join(parts)

        # 截断超长输出, 避免撑爆 LLM context
        if len(text) > _MAX_OUTPUT:
            text = text[:_MAX_OUTPUT] + f"\n... (输出已截断, 共 {len(text)} 字符)"

        return ToolResult(output=text)
