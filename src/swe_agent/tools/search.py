"""搜索工具: grep (内容) / glob (文件名)。

优先用系统装的 ripgrep (rg), 没有就降级到纯 Python 实现。
这样不强制依赖外部二进制, 又能在有 rg 时享受它的速度。
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

from swe_agent.tools.base import Tool, ToolError, ToolResult


def _ws_root(workspace: str) -> Path:
    return Path(workspace).resolve()


def _has_ripgrep() -> bool:
    return shutil.which("rg") is not None


# ────────────────────────────────────────────────────────────────


class GrepTool(Tool):
    name = "grep"
    description = (
        "在 workspace 内按正则搜索文件内容, 返回匹配行 (含文件名和行号)。"
        "用于定位符号/定义/用法。pattern 是正则表达式。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式"},
                "glob": {
                    "type": "string",
                    "description": "可选, 限定文件名通配 (如 *.py)",
                },
            },
            "required": ["pattern"],
        }

    def run(self, *, pattern: str, glob: str | None = None) -> ToolResult:
        root = _ws_root(self.workspace)
        # 校验正则合法性, 别让坏 pattern 让工具崩
        try:
            re.compile(pattern)
        except re.error as e:
            raise ToolError(f"非法正则: {e}")

        if _has_ripgrep():
            return self._grep_rg(root, pattern, glob)
        return self._grep_py(root, pattern, glob)

    def _grep_rg(self, root: Path, pattern: str, glob: str | None) -> ToolResult:
        cmd = ["rg", "-n", "--no-heading", "-e", pattern, str(root)]
        if glob:
            cmd += ["-g", glob]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False
            )
        except subprocess.TimeoutExpired:
            raise ToolError("grep 超时")
        out = proc.stdout.strip()
        return ToolResult(output=out if out else "(无匹配)")

    def _grep_py(self, root: Path, pattern: str, glob: str | None) -> ToolResult:
        regex = re.compile(pattern)
        hits: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if glob and not fnmatch.fnmatch(path.name, glob):
                continue
            if _is_likely_binary(path):
                continue
            try:
                for i, line in enumerate(
                    path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                ):
                    if regex.search(line):
                        rel = path.relative_to(root).as_posix()
                        hits.append(f"{rel}:{i}:{line}")
            except (OSError, UnicodeDecodeError):
                continue
            if len(hits) >= 500:  # 防爆
                hits.append("... (结果过多, 已截断)")
                break
        return ToolResult(output="\n".join(hits) if hits else "(无匹配)")


# ────────────────────────────────────────────────────────────────


class GlobTool(Tool):
    name = "glob"
    description = (
        "按文件名通配模式查找文件 (递归)。"
        "用于按名字定位文件, 如 '**/*.py' 找所有 Python 文件。"
    )

    def __init__(self, workspace: str):
        self.workspace = workspace

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "通配模式, 如 '**/*.py' 或 'src/**/*.ts'",
                },
            },
            "required": ["pattern"],
        }

    def run(self, *, pattern: str) -> ToolResult:
        root = _ws_root(self.workspace)
        # Path.glob 支持 ** 递归
        try:
            matched = sorted(root.glob(pattern))
        except (ValueError, OSError) as e:
            raise ToolError(f"glob 失败: {e}")
        rels = [
            p.relative_to(root).as_posix() for p in matched if not p.is_dir()
        ]
        return ToolResult(output="\n".join(rels) if rels else "(无匹配)")


def _is_likely_binary(path: Path, peek: int = 1024) -> bool:
    """粗略判断是否二进制: 读一小段看有没有 NUL 字节。"""
    try:
        with path.open("rb") as f:
            chunk = f.read(peek)
        return b"\x00" in chunk
    except OSError:
        return True
