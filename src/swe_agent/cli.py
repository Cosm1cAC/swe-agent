"""命令行入口 (CLI / REPL)。

集成 TUI 全屏窗口模式 (Rich Live + Layout)。

--task 模式: 无 TUI, 传统输出
--tui / --no-tui: 控制是否启用全屏窗口风格
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Callable

from rich.console import Console
from rich.table import Table

from swe_agent import __version__
from swe_agent.agent import Agent, AgentEvent, AgentRunResult
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
        prog="swe-agent",
        description="Minimal SWE Agent — 一个学习用的 ReAct 软件工程智能体。",
    )
    p.add_argument("--version", action="version", version=f"swe-agent {__version__}")
    p.add_argument("--check", action="store_true", help="只检查配置是否就绪, 不启动 agent。")
    p.add_argument(
        "--task", type=str, default=None,
        help="直接给一个任务描述 (非交互模式)。不给则进入 REPL。",
    )
    p.add_argument("--workspace", type=str, default=".", help="agent 的工作目录 (默认当前目录)。")
    p.add_argument("--max-steps", type=int, default=None, help="最大步数 (默认读 .env 的 MAX_STEPS)。")
    p.add_argument(
        "--tui", action="store_true", default=None,
        help="启用全屏窗口式 TUI (默认: REPL 模式启用, --task 模式禁用)。",
    )
    p.add_argument(
        "--no-tui", action="store_false", dest="tui", default=None,
        help="禁用全屏窗口式 TUI, 使用传统输出。",
    )
    return p


# ── 事件打印 (传统模式) ──────────────────────────────────────


def make_event_printer():
    """构造 AgentEvent 的彩色打印 callback (非 TUI 模式用)。"""

    def _print(ev: AgentEvent) -> None:
        if ev.kind == "think":
            console.print(
                f"  [blue]💭 step{ev.step} 思考:[/] {ev.content}"
            )
        elif ev.kind == "tool_call":
            tc = ev.tool_call
            args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
            console.print(
                f"  [magenta]▶ step{ev.step} 调用:[/] [yellow]{tc.name}[/]({args_str})"
            )
        elif ev.kind == "tool_result":
            out = ev.tool_output or ""
            if len(out) > 1500:
                out = out[:1500] + f"\n... (共 {len(out)} 字符, 已截断)"
            console.print(
                f"     [green]← 结果:[/] {out}"
            )
        elif ev.kind == "done":
            console.print(f"  [bold green][OK] 完成:[/] {ev.content}")
        elif ev.kind == "error":
            console.print(f"  [red][X] 错误:[/] {ev.error}")
        elif ev.kind == "step_limit":
            console.print(f"  [yellow][!] 达到步数上限 ({ev.step}), 终止。[/]")

    return _print


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


# ── 执行任务 (传统模式) ──────────────────────────────────────


def run_task(cfg: Config, task: str, workspace: str, max_steps: int | None) -> int:
    agent = build_agent(cfg, workspace, max_steps)
    console.print(f"[dim]━━━━━━ 任务: {task} ━━━━━━[/]\n")
    result: AgentRunResult = agent.run(task, callback=make_event_printer())

    status = "[green][OK] 完成[/]" if result.finished else "[yellow][!] 未完成[/]"
    console.print(
        f"\n[dim]━━━━ 共 {result.steps} 步, "
        f"约 {result.total_tokens} tokens, "
        f"{status}"
        f" ━━━━[/]\n"
    )

    _session.runs += 1
    _session.total_steps += result.steps
    _session.total_tokens += result.total_tokens

    return 0 if result.finished else 1


# ── 执行任务 (TUI 全屏模式) ─────────────────────────────────


def run_task_tui(cfg: Config, task: str, workspace: str, max_steps: int | None) -> int:
    tui = TUI(cfg, workspace)  # 只用来做回调, 不管理 Live
    agent = build_agent(cfg, workspace, max_steps)

    # 先打印一条分割线, 再进入全屏
    console.print(f"[dim]━━━━━━ 任务: {task} ━━━━━━[/]\n")

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


def run_repl(cfg: Config, workspace: str, max_steps: int | None, use_tui: bool) -> int:
    tui = TUI(cfg, workspace) if use_tui else None

    if tui:
        tui.show_splash()
    else:
        print_banner(cfg, workspace)

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
            if use_tui:
                run_task_tui(cfg, line, workspace, max_steps)
            else:
                run_task(cfg, line, workspace, max_steps)
        except KeyboardInterrupt:
            console.print("\n[yellow][!] 已中断当前任务[/]\n")
        except Exception as e:  # noqa: BLE001 — 兜底
            console.print(f"[red][X] 异常: {e}[/]\n")


def print_banner(cfg: Config, workspace: str) -> None:
    """传统模式启动横幅。"""
    model = cfg.openai_model if cfg.provider == "openai" else cfg.anthropic_model
    tools = build_default_tools(workspace)
    n_tools = len(tools.names())
    console.print(
        f"[bold cyan]═══ Minimal SWE Agent v{__version__} ═══[/]\n"
        f"[dim]模型:[/] {model}\n"
        f"[dim]工具:[/] {n_tools} 个 ({', '.join(tools.names())})\n"
        f"[dim]步数上限:[/] {cfg.max_steps}\n"
        f"[dim]工作目录:[/] {workspace}\n"
        f"\n"
        f"输入任务描述后回车开始, 或输入 [yellow]/help[/] 查看帮助\n"
    )


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

    # TUI 默认策略: REPL 开, --task 关
    use_tui = args.tui if args.tui is not None else (args.task is None)

    if args.task:
        if use_tui:
            return run_task_tui(cfg, args.task, args.workspace, args.max_steps)
        return run_task(cfg, args.task, args.workspace, args.max_steps)

    return run_repl(cfg, args.workspace, args.max_steps, use_tui)


if __name__ == "__main__":
    sys.exit(main())
