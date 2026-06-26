"""文件系统工具: read / write / edit / list。

【安全设计】
  所有路径都相对于 workspace 解析, 并做"路径逃逸"检查,
  不允许 .. 跳到 workspace 之外 —— 防止 agent 误改系统文件。

【edit_file 为什么是关键工具】
  写代码时, 整文件重写 (write_file) 既费 token 又容易丢内容。
  精确字符串替换 (edit_file) 只需指定 old/new 片段,
  token 省、改动小、更接近"人类改代码"的方式。
  ZCode / Aider / Claude Code 的核心编辑工具都是这个思路。
"""
from __future__ import annotations

import os
from pathlib import Path

from swe_agent.tools.base import Tool, ToolError, ToolResult

# 读文件时超过这个行数就提示 agent 文件很大 (不截断, 只提醒)
_LARGE_FILE_THRESHOLD = 2000


def _resolve(workspace: str, path: str) -> Path:
    """把相对路径解析到 workspace 内, 并防止路径逃逸。

    raises ToolError: 路径逃出 workspace。
    """
    ws = Path(workspace).resolve()
    # 先 join 再 resolve, 然后检查是否还在 ws 之下
    full = (ws / path).resolve()
    try:
        full.relative_to(ws)
    except ValueError:
        raise ToolError(f"路径越界 (必须在 workspace 内): {path}")
    return full


# ────────────────────────────────────────────────────────────────


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "读取指定文本文件的内容。用于查看代码、配置等。"
        "返回文件全文 (带行号)。路径相对于 workspace。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径"},
            },
            "required": ["path"],
        }

    def run(self, *, path: str) -> ToolResult:
        full = _resolve(self.workspace, path)
        if not full.exists():
            raise ToolError(f"文件不存在: {path}")
        if full.is_dir():
            raise ToolError(f"目标是目录, 不能用 read_file: {path}")
        try:
            text = full.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # 二进制文件兜底
            raise ToolError(f"无法以文本读取 (可能是二进制文件): {path}")

        lines = text.splitlines()
        # 带行号返回, 方便后续 edit_file 定位
        numbered = "\n".join(f"{i + 1:5}\t{ln}" for i, ln in enumerate(lines))
        note = ""
        if len(lines) > _LARGE_FILE_THRESHOLD:
            note = f"\n\n[提示] 文件较大 ({len(lines)} 行), 可考虑只读必要部分。\n"
        return ToolResult(output=f"{numbered}{note}")


# ────────────────────────────────────────────────────────────────


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "将内容写入文件 (覆盖写入)。文件不存在则创建 (含父目录)。"
        "用于创建新文件或整体重写。路径相对于 workspace。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        }

    def run(self, *, path: str, content: str) -> ToolResult:
        full = _resolve(self.workspace, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        n_lines = content.count("\n") + (0 if content.endswith("\n") else 1)
        return ToolResult(output=f"已写入 {path} ({n_lines} 行)")


# ────────────────────────────────────────────────────────────────


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "对已有文件做精确字符串替换。old_string 必须在文件中唯一出现, "
        "否则报错 (避免改错地方)。用于小范围修改代码, 比 write_file 更省更安全。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "old_string": {"type": "string", "description": "要被替换的原文本 (须唯一)"},
                "new_string": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def run(self, *, path: str, old_string: str, new_string: str) -> ToolResult:
        full = _resolve(self.workspace, path)
        if not full.exists():
            raise ToolError(f"文件不存在: {path}")

        text = full.read_text(encoding="utf-8")
        count = text.count(old_string)

        if count == 0:
            # 给 LLM 够多信息让它自我纠正: 列出可能相近的行
            raise ToolError(
                f"old_string 在文件中未找到。请先用 read_file 确认内容。"
            )
        if count > 1:
            raise ToolError(
                f"old_string 在文件中出现 {count} 次, 不唯一。"
                "请扩大上下文让 old_string 唯一匹配。"
            )

        new_text = text.replace(old_string, new_string, 1)
        full.write_text(new_text, encoding="utf-8")
        return ToolResult(output=f"已替换 {path} 中 1 处")


# ────────────────────────────────────────────────────────────────


class ListDirTool(Tool):
    name = "list_dir"
    description = (
        "列出目录内容 (递归一层, 带类型标记)。"
        "用于了解项目结构。路径相对于 workspace, 默认为根。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径, 默认为 workspace 根",
                    "default": ".",
                },
            },
            "required": [],
        }

    def run(self, *, path: str = ".") -> ToolResult:
        full = _resolve(self.workspace, path)
        if not full.exists():
            raise ToolError(f"目录不存在: {path}")
        if not full.is_dir():
            raise ToolError(f"不是目录: {path}")

        rows = []
        for child in sorted(full.iterdir()):
            tag = "/" if child.is_dir() else ""
            rows.append(f"{child.name}{tag}")
        if not rows:
            return ToolResult(output="(空目录)")
        return ToolResult(output="\n".join(rows))
