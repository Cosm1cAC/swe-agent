"""终端 UI 管理器: 全屏式"窗口化" ReAct 交互界面。

在任务执行期间用 Rich Live + Layout 进入 alt-screen 全屏模式,
渲染固定顶栏 + 滚动事件流 + 底栏状态, 营造类似 htop/vim 的
"命令行窗口"体验。任务结束后恢复终端原内容并显示摘要。
"""
from __future__ import annotations

from typing import Callable

from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from swe_agent import __version__
from swe_agent.agent import AgentEvent, AgentRunResult, Callback
from swe_agent.config import Config
from swe_agent.tools import build_default_tools


class TUI:
    """全屏终端 UI 管理器。

    用法::
        tui = TUI(cfg, workspace)
        tui.show_splash()
        # 输入循环:
        cb = tui.start_task("修复 bug")
        agent.run("修复 bug", callback=cb)
        tui.end_task(result)
    """

    def __init__(self, cfg: Config, workspace: str) -> None:
        self.cfg = cfg
        self.workspace = workspace
        self.console = Console()
        self._live: Live | None = None
        self._layout: Layout | None = None
        self._events: list[RenderableType] = []
        self._model = (
            cfg.openai_model if cfg.provider == "openai" else cfg.anthropic_model
        )

    # ── 启动画面 (正常终端区域, 非全屏) ─────────────────────

    def show_splash(self) -> None:
        """打印启动信息。"""
        tools = build_default_tools(self.workspace)
        n_tools = len(tools.names())
        self.console.rule(f"[bold cyan]Minimal SWE Agent[/] [dim]v{__version__}[/]")
        self.console.print(
            f"  [dim]模型:[/]  {self._model}\n"
            f"  [dim]工具:[/]  {n_tools} 个 ({', '.join(tools.names())})\n"
            f"  [dim]步数上限:[/]  {self.cfg.max_steps}\n"
            f"  [dim]工作目录:[/]  {self.workspace}\n"
        )
        self.console.print(
            "  输入任务描述后回车开始  |  "
            "[yellow]/help[/] 查看帮助  |  "
            "[yellow]/quit[/] 退出\n"
        )

    # ── 任务执行 (全屏 Live) ───────────────────────────────

    def start_task(self, task: str) -> Callback:
        """进入 alt-screen 全屏模式并返回 Agent 事件回调。

        在 Live 期间终端进入独立缓冲区, 显示窗口式 UI:
          顶栏 — 版本、模型名、当前任务
          主体 — 事件流 (思考/调用/结果 Panel)
          底栏 — 进度 + 状态
        结束后自动恢复终端原内容。
        """
        self._events = []

        self._layout = Layout()
        self._layout.split(
            Layout(
                name="header",
                size=4,
                renderable=self._build_header(task),
            ),
            Layout(name="body"),
            Layout(
                name="footer",
                size=1,
                renderable=Text(" ⏳ 运行中...", style="dim italic"),
            ),
        )

        self._live = Live(
            self._layout,
            screen=True,
            auto_refresh=True,
            refresh_per_second=8,
            console=self.console,
        )
        self._live.__enter__()
        return self._on_event

    def end_task(self, result: AgentRunResult) -> None:
        """退出全屏模式、恢复终端并打印任务摘要。"""
        self._exit_live()

        status_tag = (
            "[green][OK] 完成[/]"
            if result.finished
            else "[yellow][!] 未完成[/]"
        )
        self.console.rule(
            f"[dim]共 {result.steps} 步 · "
            f"约 {result.total_tokens} tokens · "
            f"{status_tag}[/]"
        )
        self.console.print()

    def interrupt_task(self) -> None:
        """Ctrl+C 打断时安全退出 Live 并打印提示。"""
        self._exit_live()
        self.console.print("[yellow][!] 已中断当前任务[/]\n")

    def fail_task(self, error: str) -> None:
        """异常退出时清理并打印错误。"""
        self._exit_live()
        self.console.print(f"[red][X] 异常: {error}[/]\n")

    # ── 内部：组件渲染 ────────────────────────────────────

    def _exit_live(self) -> None:
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None

    def _build_header(self, task: str) -> Panel:
        title = (
            f" ═══ Minimal SWE Agent v{__version__}  —  {self._model} ═══ "
        )
        subtitle = Text(
            f" 任务: {task[:70]}{'…' if len(task) > 70 else ''}",
            style="dim",
            no_wrap=True,
            overflow="ellipsis",
        )
        return Panel(
            subtitle,
            title=title,
            border_style="cyan",
            padding=(0, 1),
            subtitle=f"workspace: {self.workspace}",
        )

    def _update_footer(self, text: str) -> None:
        if self._layout is not None:
            self._layout["footer"].update(
                Text(f" {text}", style="dim italic", no_wrap=True)
            )

    def _on_event(self, ev: AgentEvent) -> None:
        """将 AgentEvent 转为 Renderable 追加到事件流。"""
        # ── 构造当前事件的 Renderable ──────────────────────
        renderable: RenderableType | None = None
        footer_text: str | None = None

        if ev.kind == "think":
            renderable = Panel(
                Text(ev.content or "", no_wrap=False),
                title=f"[dim]step {ev.step} · 思考[/]",
                border_style="blue",
                padding=(0, 1),
            )
            footer_text = f"⟳ step {ev.step}/{self.cfg.max_steps} · 推理中"

        elif ev.kind == "tool_call":
            assert ev.tool_call is not None
            tc = ev.tool_call
            args_str = ", ".join(
                f"{k}={v!r}" for k, v in tc.arguments.items()
            )
            renderable = Text(
                f"  ▶ step {ev.step} · [yellow]{tc.name}[/]({args_str})",
                no_wrap=False,
            )
            footer_text = (
                f"⟳ step {ev.step}/{self.cfg.max_steps} · 调用 {tc.name}"
            )

        elif ev.kind == "tool_result":
            out = ev.tool_output or ""
            if len(out) > 800:
                out = out[:800] + f"\n... (共 {len(out)} 字符, 已截断)"
            renderable = Panel(
                Text(out, no_wrap=False),
                title=f"[dim]step {ev.step} · 结果[/]",
                border_style="green",
                padding=(0, 1),
            )
            footer_text = (
                f"⟳ step {ev.step}/{self.cfg.max_steps} · 观察结果"
            )

        elif ev.kind == "done":
            renderable = Panel(
                Text(ev.content or "(无内容)", style="bold green"),
                title="[bold green][OK] 完成[/]",
                border_style="green",
            )
            footer_text = "[OK] 任务完成"

        elif ev.kind == "error":
            renderable = Panel(
                Text(f"[X] {ev.error}", style="red"),
                title="[red]错误[/]",
                border_style="red",
            )
            footer_text = "[X] 发生错误"

        elif ev.kind == "step_limit":
            renderable = Panel(
                Text(
                    f"[!] 达到步数上限 ({ev.step}), 已终止。",
                    style="yellow",
                ),
                title="[yellow]步数上限[/]",
                border_style="yellow",
            )
            footer_text = "[!] 达到步数上限"

        # ── 追加并刷新 ──────────────────────────────────────
        if renderable is not None:
            self._events.append(renderable)
        if footer_text is not None:
            self._update_footer(footer_text)

        if self._live and self._layout is not None:
            self._layout["body"].update(Group(*self._events))
            self._live.refresh()
