"""工具层测试: 用临时目录实际跑每个工具, 验证行为 + 安全护栏。"""
from __future__ import annotations

from pathlib import Path

import pytest

from swe_agent.tools import ToolRegistry, build_default_tools
from swe_agent.tools.base import ToolError


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """临时 workspace, 测试结束自动清理。"""
    return tmp_path


@pytest.fixture
def reg(ws: Path) -> ToolRegistry:
    return build_default_tools(str(ws))


# ── write + read 闭环 ───────────────────────────────────────────


def test_write_then_read(ws: Path, reg: ToolRegistry):
    w = reg.execute("write_file", {"path": "a.py", "content": "print('hi')\n"})
    assert w.error is None
    r = reg.execute("read_file", {"path": "a.py"})
    assert r.error is None
    assert "print('hi')" in r.output
    # read 带行号
    assert "1" in r.output


def test_write_creates_nested_dirs(ws: Path, reg: ToolRegistry):
    r = reg.execute("write_file", {"path": "pkg/sub/b.py", "content": "x=1"})
    assert r.error is None
    assert (ws / "pkg" / "sub" / "b.py").exists()


def test_read_missing_file(reg: ToolRegistry):
    r = reg.execute("read_file", {"path": "nope.py"})
    assert r.error is not None
    assert "不存在" in r.error


def test_read_directory_error(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "f.txt", "content": "1"})
    r = reg.execute("read_file", {"path": "."})
    assert r.error is not None
    assert "目录" in r.error


# ── edit_file: 精确替换 ─────────────────────────────────────────


def test_edit_replaces_unique(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "m.py", "content": "a = 1\nb = 2\n"})
    r = reg.execute(
        "edit_file",
        {"path": "m.py", "old_string": "b = 2", "new_string": "b = 99"},
    )
    assert r.error is None
    assert "1 处" in r.output
    assert (ws / "m.py").read_text() == "a = 1\nb = 99\n"


def test_edit_not_found(reg: ToolRegistry):
    reg.execute("write_file", {"path": "m.py", "content": "hello"})
    r = reg.execute(
        "edit_file",
        {"path": "m.py", "old_string": "zzz", "new_string": "y"},
    )
    assert r.error is not None
    assert "未找到" in r.error


def test_edit_ambiguous(reg: ToolRegistry):
    reg.execute("write_file", {"path": "m.py", "content": "x\nx\n"})
    r = reg.execute(
        "edit_file",
        {"path": "m.py", "old_string": "x", "new_string": "y"},
    )
    assert r.error is not None
    assert "2 次" in r.error or "不唯一" in r.error


# ── list_dir ────────────────────────────────────────────────────


def test_list_dir(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "a.py", "content": "1"})
    reg.execute("write_file", {"path": "b.txt", "content": "2"})
    (ws / "sub").mkdir()
    r = reg.execute("list_dir", {"path": "."})
    assert r.error is None
    assert "a.py" in r.output
    assert "b.txt" in r.output
    assert "sub/" in r.output  # 目录带斜杠标记


def test_list_empty_dir(ws: Path, reg: ToolRegistry):
    r = reg.execute("list_dir", {"path": "."})
    assert r.error is None
    assert "空目录" in r.output


# ── search: grep / glob ─────────────────────────────────────────


def test_grep_finds(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "a.py", "content": "def foo():\n    pass\n"})
    reg.execute("write_file", {"path": "b.py", "content": "def bar():\n    pass\n"})
    r = reg.execute("grep", {"pattern": "def foo"})
    assert r.error is None
    assert "a.py" in r.output
    assert "def foo" in r.output


def test_grep_glob_filter(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "a.py", "content": "target"})
    reg.execute("write_file", {"path": "a.txt", "content": "target"})
    r = reg.execute("grep", {"pattern": "target", "glob": "*.py"})
    assert r.error is None
    assert "a.py" in r.output
    assert "a.txt" not in r.output


def test_grep_invalid_regex(reg: ToolRegistry):
    r = reg.execute("grep", {"pattern": "(unclosed"})
    assert r.error is not None
    assert "正则" in r.error


def test_glob_finds(ws: Path, reg: ToolRegistry):
    reg.execute("write_file", {"path": "x.py", "content": "1"})
    reg.execute("write_file", {"path": "sub/y.py", "content": "2"})
    (ws / "sub").mkdir(exist_ok=True)
    reg.execute("write_file", {"path": "sub/y.py", "content": "2"})
    r = reg.execute("glob", {"pattern": "**/*.py"})
    assert r.error is None
    assert "x.py" in r.output
    assert "sub/y.py" in r.output or "y.py" in r.output


# ── shell ───────────────────────────────────────────────────────


def test_shell_success(reg: ToolRegistry):
    r = reg.execute("run_shell", {"command": "echo hello"})
    assert r.error is None
    assert "hello" in r.output
    assert "exit code: 0" in r.output


def test_shell_nonzero_exit(reg: ToolRegistry):
    # 用一个必然失败的命令
    r = reg.execute("run_shell", {"command": "exit 3"})
    assert r.error is None  # 非零退出不算 ToolError, 是正常的"执行结果"
    assert "exit code: 3" in r.output


# ── 安全: 路径逃逸防护 ──────────────────────────────────────────


def test_path_escape_blocked(ws: Path, reg: ToolRegistry):
    r = reg.execute("read_file", {"path": "../../../etc/passwd"})
    assert r.error is not None
    assert "越界" in r.error


def test_unknown_tool_handled(reg: ToolRegistry):
    """调用不存在的工具, 应返回 error 而非抛异常。"""
    r = reg.execute("no_such_tool", {})
    assert r.error is not None
    assert "未知工具" in r.error


def test_tool_arg_error_caught(reg: ToolRegistry):
    """工具缺关键参数, 应被 registry 兜底, 不崩。"""
    r = reg.execute("write_file", {"path": "x.py"})  # 缺 content
    assert r.error is not None
