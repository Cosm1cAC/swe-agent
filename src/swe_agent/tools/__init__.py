"""工具集: 文件读写、搜索、Shell 执行。

对外提供:
  - Tool / ToolResult / ToolError  基类与协议
  - ToolRegistry                    工具注册表 (门面)
  - build_default_tools(workspace)  构造默认工具集
"""
from swe_agent.tools.base import Tool, ToolError, ToolResult
from swe_agent.tools.registry import ToolRegistry, build_default_tools

__all__ = ["Tool", "ToolResult", "ToolError", "ToolRegistry", "build_default_tools"]
