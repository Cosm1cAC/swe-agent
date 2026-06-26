"""
端到端演示: 用 ScriptedLLM 模拟 agent 修复一个 bug 的全过程。

【为什么用 mock】
  沙箱可能无法联网调真实 LLM。这个脚本用一个"剧本式"假 LLM,
  完整展示 agent 真实跑起来时的样子:
    读代码 -> 发现问题 -> 修复 -> 跑测试验证 -> 完成

  它和真实 agent 的唯一区别, 只是 LLM 的回复是预设的。
  换成真 key 后, 同一个 Agent 会自己产出这些决策。

运行: python demo_mock.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from rich.console import Console

from swe_agent.agent import Agent, AgentEvent
from swe_agent.llm.base import LLMResponse, ToolCall
from swe_agent.tools import build_default_tools

console = Console()


class ScriptedLLM:
    """剧本式假 LLM。"""

    def __init__(self, script, model="mock"):
        self.model = model
        self._script = list(script)
        self._i = 0

    def chat(self, messages, tools=None, *, temperature=0.0):
        resp = self._script[self._i]
        self._i += 1
        return resp


def _tc(name, args, id_):
    return ToolCall(name=name, arguments=args, id=id_)


def printer(ev: AgentEvent) -> None:
    if ev.kind == "think":
        console.print(
            f"  [blue]💭 step{ev.step} 思考:[/] {ev.content}"
        )
    elif ev.kind == "tool_call":
        tc = ev.tool_call
        args = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
        console.print(f"  [magenta]▶ step{ev.step} 调用:[/] [yellow]{tc.name}[/]({args})")
    elif ev.kind == "tool_result":
        out = (ev.tool_output or "").replace("\n", "\n     ")
        if len(out) > 200:
            out = out[:200] + "..."
        console.print(f"     [green]← 结果:[/] {out}")
    elif ev.kind == "done":
        console.print(f"  [bold green]✓ 完成:[/] {ev.content}")
    elif ev.kind == "step_limit":
        console.print(f"  [yellow]⚠ 步数上限[/]")
    elif ev.kind == "error":
        console.print(f"  [red]✗ 错误:[/] {ev.error}")


def main():
    # 准备一个"有 bug"的项目
    ws = Path(tempfile.mkdtemp(prefix="swe_demo_"))
    buggy = "def add(a, b):\n    return a - b  # bug! 应该是 +\n"
    (ws / "calc.py").write_text(buggy, encoding="utf-8")
    test = (
        "from calc import add\n"
        "assert add(1, 2) == 3, f'got {add(1,2)}'\n"
        "print('test passed')\n"
    )
    (ws / "test_calc.py").write_text(test, encoding="utf-8")

    console.print(f"[bold cyan]═══ Minimal SWE Agent 端到端演示 ═══[/]")
    console.print(f"[dim]workspace: {ws}[/]")
    console.print(f"[dim]任务: 'test_calc.py 失败了, 修复它'[/]\n")

    # 剧本: 模拟一个聪明的 agent 修 bug 的完整决策链
    script = [
        # step1: 先看测试文件了解在测什么
        LLMResponse(
            content="我先看看测试在测什么。",
            tool_calls=[_tc("read_file", {"path": "test_calc.py"}, "c1")],
        ),
        # step2: 再看被测代码
        LLMResponse(
            content="测试期望 add(1,2)==3。看看 add 的实现。",
            tool_calls=[_tc("read_file", {"path": "calc.py"}, "c2")],
        ),
        # step3: 发现 bug, 修复
        LLMResponse(
            content="发现 bug: add 里用了减号, 应该是加号。修复它。",
            tool_calls=[
                _tc(
                    "edit_file",
                    {"path": "calc.py", "old_string": "return a - b", "new_string": "return a + b"},
                    "c3",
                )
            ],
        ),
        # step4: 跑测试验证
        LLMResponse(
            content="跑测试确认修复有效。",
            tool_calls=[_tc("run_shell", {"command": "python test_calc.py"}, "c4")],
        ),
        # step5: 完成
        LLMResponse(content="测试通过, bug 已修复 (a-b 改为 a+b)。", tool_calls=[]),
    ]

    agent = Agent(ScriptedLLM(script), build_default_tools(str(ws)), max_steps=10)
    result = agent.run("test_calc.py 失败了, 修复它", callback=printer)

    console.print()
    console.print(
        f"[dim]── {result.steps} 步, ~{result.total_tokens} tokens, "
        f"{'✓完成' if result.finished else '✗未完成'} ──[/]"
    )
    console.print(f"[dim]修复后 calc.py:[/]\n[green]{(ws/'calc.py').read_text()}[/]")
    return 0 if result.finished else 1


if __name__ == "__main__":
    sys.exit(main())
