"""命令行入口 — 全屏 TUI 模式 (对标 Claude Code CLI)。

始终使用 Rich Live + Layout 全屏窗口式界面, 不再支持传统逐行输出。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Callable

from rich.console import Console
from rich.table import Table

from swe_agent import __version__
from swe_agent.agent import Agent, AgentRunResult
from swe_agent.config import Config
from swe_agent.llm import make_llm
from swe_agent.tools import build_default_tools
from swe_agent.tui import TUI

console = Console()

# ── 全局跟踪 (跨任务统计) ──────────────────────────────────────


@dataclass
class SessionStats:
    runs: int = 0
    total_steps: int = 0
    total_tokens: int = 0


_session = SessionStats()


# ── 参数解析 ──────────────────────────────────────────────────


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="swe-cli",
        description="Mini SWE CLI — 一个基于 ReAct 循环的软件工程命令行智能体。",
    )
    p.add_argument("--version", action="version", version=f"swe-cli {__version__}")
    p.add_argument(
        "--check", action="store_true",
        help="只检查配置是否就绪, 不启动 agent。",
    )
    p.add_argument(
        "--task", type=str, default=None,
        help="直接给一个任务描述 (非交互模式)。不给则进入 REPL。",
    )
    p.add_argument(
        "--workspace", type=str, default=".",
        help="agent 的工作目录 (默认当前目录)。",
    )
    p.add_argument(
        "--max-steps", type=int, default=None,
        help="最大步数 (默认读 .env 的 MAX_STEPS)。",
    )
    return p


# ── 斜杠命令 ──────────────────────────────────────────────────


COMMANDS: dict[str, tuple[str, Callable]] = {}


def _cmd_help(cfg: Config, _ws: str, _arg: str) -> None:
    table = Table(title="可用命令", show_header=False, border_style="dim")
    table.add_column(style="bold yellow", no_wrap=True)
    table.add_column(style="dim")
    for name, (desc, _) in sorted(COMMANDS.items()):
        table.add_row(f"/{name}", desc)
    table.add_row("/<任务描述>", "直接开始执行任务")
    console.print(table)


def _cmd_model(cfg: Config, _ws: str, _arg: str) -> None:
    if cfg.provider == "openai":
        model, api, key = cfg.openai_model, cfg.openai_base_url, cfg.openai_api_key[:8]
    else:
        model, api, key = cfg.anthropic_model, "Anthropic", cfg.anthropic_api_key[:8]
    console.print(
        f"[dim]provider:[/] {cfg.provider}\n"
        f"[dim]model:[/] {model}\n"
        f"[dim]endpoint:[/] {api}\n"
        f"[dim]api_key:[/] {key}..."
    )


def _cmd_config(cfg: Config, _ws: str, _arg: str) -> None:
    console.print(repr(cfg))


def _cmd_tokens(_cfg: Config, _ws: str, _arg: str) -> None:
    if _session.runs == 0:
        console.print("[dim]尚无历史记录。[/]")
    else:
        console.print(
            f"[dim]累计:[/] {_session.runs} 次任务, "
            f"{_session.total_steps} 步, "
            f"约 {_session.total_tokens} tokens"
        )


COMMANDS["help"] = ("显示本帮助", _cmd_help)
COMMANDS["model"] = ("查看当前模型配置", _cmd_model)
COMMANDS["config"] = ("查看完整配置 (不含 key)", _cmd_config)
COMMANDS["tokens"] = ("查看累计 token 用量", _cmd_tokens)


def handle_slash(cfg: Config, workspace: str, line: str) -> bool:
    """处理斜杠命令。返回 True 代表已处理 (不执行 agent)。"""
    parts = line[len("/"):].strip().split(maxsplit=1)
    cmd_name = parts[0].lower()
    cmd_arg = parts[1] if len(parts) > 1 else ""
    entry = COMMANDS.get(cmd_name)
    if entry is None:
        console.print(f"[red]未知命令: /{cmd_name}[/]。输入 /help 查看可用命令。")
        return True
    _, fn = entry
    fn(cfg, workspace, cmd_arg)
    return True


# ── 构建 Agent ────────────────────────────────────────────────


def build_agent(cfg: Config, workspace: str, max_steps: int | None) -> Agent:
    llm = make_llm(cfg)
    tools = build_default_tools(workspace)
    return Agent(llm, tools, max_steps=max_steps or cfg.max_steps)


# ── 执行任务 (TUI 全屏模式) ─────────────────────────────────


def run_task(cfg: Config, task: str, workspace: str, max_steps: int | None) -> int:
    tui = TUI(cfg, workspace)
    agent = build_agent(cfg, workspace, max_steps)

    result: AgentRunResult | None = None
    try:
        event_cb = tui.start_task(task)
        result = agent.run(task, callback=event_cb)
        tui.end_task(result)
    except KeyboardInterrupt:
        tui.interrupt_task()
        return 130
    except Exception as e:  # noqa: BLE001 — 兜底
        tui.fail_task(str(e))
        return 1

    _session.runs += 1
    _session.total_steps += result.steps
    _session.total_tokens += result.total_tokens

    status = "[green][OK] 完成[/]" if result.finished else "[yellow][!] 未完成[/]"
    console.print(
        f"[dim]共 {result.steps} 步 · "
        f"约 {result.total_tokens} tokens · "
        f"{status}[/]\n"
    )

    return 0 if result.finished else 1


# ── REPL ──────────────────────────────────────────────────────


def run_repl(cfg: Config, workspace: str, max_steps: int | None) -> int:
    tui = TUI(cfg, workspace)
    tui.show_splash()

    while True:
        try:
            line = console.input("[bold green]task>[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/]")
            return 0

        line = line.strip()
        if not line:
            continue

        # 退出命令
        if line in (":q", ":quit", ":exit", "/q", "/quit"):
            console.print("[dim]bye[/]")
            return 0

        # 斜杠命令
        if line.startswith("/"):
            handle_slash(cfg, workspace, line)
            continue

        # 执行任务
        console.print()
        try:
            run_task(cfg, line, workspace, max_steps)
        except KeyboardInterrupt:
            console.print("\n[yellow][!] 已中断当前任务[/]\n")
        except Exception as e:  # noqa: BLE001 — 兜底
            console.print(f"[red][X] 异常: {e}[/]\n")


# ── 入口 ──────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = Config()

    problems = cfg.validate()
    if problems:
        console.print("[red][X] 配置不完整:[/]")
        for p in problems:
            console.print(f"  [red]- {p}[/]")
        console.print("[dim]请参考 .env.example 配置 .env[/]")
        return 2

    if args.check:
        console.print(f"[green][OK] 配置就绪[/]  {cfg}")
        return 0

    if args.task:
        return run_task(cfg, args.task, args.workspace, args.max_steps)

    return run_repl(cfg, args.workspace, args.max_steps)


if __name__ == "__main__":
    sys.exit(main())
