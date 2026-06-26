"""工具注册表: 把一堆工具组织起来, 给 Agent Loop 一个统一接口。

职责:
  - 注册工具 (按 name 索引)
  - 导出所有工具的 schema (一次性喂给 LLM)
  - 按 name 执行某个工具 (Agent Loop 收到 ToolCall 后调用)

这是工具层的"门面": Agent Loop 只跟 ToolRegistry 打交道,
不直接接触各个具体工具类。
"""
from __future__ import annotations

from swe_agent.llm.base import ToolSchema
from swe_agent.tools.base import Tool, ToolError, ToolResult


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for t in (tools or []):
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[ToolSchema]:
        """导出全部工具的 schema, 喂给 LLM。"""
        return [t.schema() for t in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, arguments: dict) -> ToolResult:
        """执行指定工具。

        - 工具不存在: 返回 ToolResult(error=...) (而不是抛异常)
        - 工具内部抛 ToolError: 转成 ToolResult(error=...)
        - 工具内部抛其它异常: 同样兜底, 不让 agent 崩
        这样 LLM 总能拿到一个文本回应, 有机会自我纠正。
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(error=f"未知工具: {name!r}")

        try:
            return tool.run(**arguments)
        except ToolError as e:
            return ToolResult(error=str(e))
        except Exception as e:  # noqa: BLE001 — 兜底, 不能让 agent 崩
            return ToolResult(error=f"{type(e).__name__}: {e}")


def build_default_tools(workspace: str = ".") -> ToolRegistry:
    """构造默认工具集 (Agent 启动时调用)。

    workspace: 文件类工具操作的根目录, 限制 agent 只能在这个范围内读写,
    避免它乱改系统其它文件 (安全护栏)。
    """
    # 延迟 import, 避免循环依赖 / 减少 base 模块加载开销
    from swe_agent.tools.fs import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        WriteFileTool,
    )
    from swe_agent.tools.search import GlobTool, GrepTool
    from swe_agent.tools.shell import RunShellTool

    return ToolRegistry(
        [
            ReadFileTool(workspace),
            WriteFileTool(workspace),
            EditFileTool(workspace),
            ListDirTool(workspace),
            GrepTool(workspace),
            GlobTool(workspace),
            RunShellTool(workspace),
        ]
    )
