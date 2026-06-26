# Minimal SWE Agent

一个 **用于学习** 的、基于 **ReAct 循环**（Reason + Act）的软件工程智能体。

代码刻意精简、分层清晰，目标是让你读懂每一行，理解一个 coding agent 是怎么搭起来的。

## 它能做什么

给它一个任务（修个 bug、加个小功能、写段脚本），它会：

1. **理解任务** — 阅读你的代码（`read_file` / `list_dir` / `grep`）
2. **思考方案** — LLM 推理，决定下一步行动
3. **动手修改** — `edit_file` 精确替换 / `write_file` 创建文件
4. **验证结果** — `run_shell` 跑测试或执行命令
5. **反复迭代** — 直到任务完成或达到步数上限

全部在 **REPL** 交互式环境中完成，支持斜杠命令和跨任务统计。

## 快速开始

```bash
# 1. 安装 (开发模式)
pip install -e ".[dev]"

# 2. 配置: 复制模板并填入 API key
cp .env.example .env
#   编辑 .env, 至少填 OPENAI_API_KEY

# 3. 检查配置是否就绪
python -m swe_agent --check

# 4. 启动 REPL
python -m swe_agent
```

**或者一次执行**：
```bash
python -m swe_agent --task "修复 test_calc.py 中的 bug"
```

### 无 API key 也能体验

项目附带一个 mock 演示，用预设剧本模拟完整 agent 流程，无需任何 API key：

```bash
python demo_mock.py
```

你会看到 agent 读代码 → 发现 bug → 修复 → 跑测试 → 完成的完整过程。

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户任务                               │
└────────────────────┬────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────┐
│              CLI / REPL  (cli.py)                        │
│  斜杠命令 /help /model /config /tokens                   │
│  彩色输出 · 跨任务统计 · 启动横幅                        │
└────────────────────┬────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Agent Loop (agent/loop.py)                   │
│           ReAct: 思考 → 行动 → 观察                      │
│         ┌───────────────┴───────────────┐                │
│         ▼                               ▼                │
│  ┌──────────────┐           ┌──────────────────┐         │
│  │  LLM 抽象层   │           │   工具集          │         │
│  │ (llm/)       │           │  (tools/)        │         │
│  │              │           │                  │         │
│  │ OpenAI       │           │  ReadFileTool    │         │
│  │ Anthropic    │           │  WriteFileTool   │         │
│  │ 可扩展更多    │           │  EditFileTool    │         │
│  └──────────────┘           │  ListDirTool     │         │
│                              │  GrepTool        │         │
│                              │  GlobTool        │         │
│                              │  RunShellTool    │         │
│                              └──────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

**设计精髓**：LLM 层和工具层都被抽象为接口，Agent Loop 只依赖抽象。
- 换模型（OpenAI → Anthropic）只需改 `.env` 的一行 `LLM_PROVIDER=anthropic`
- 加工具只需实现 `Tool` 抽象类并注册
- 核心逻辑与显示完全分离（Callback 模式）

## 目录结构

```
src/swe_agent/
├── __init__.py        版本信息
├── __main__.py        入口: python -m swe_agent
├── cli.py             命令行 + REPL (argparse, 斜杠命令, 彩色输出)
├── config.py          配置加载 (环境变量 / .env)
├── llm/
│   ├── base.py        Message / ToolCall / LLMResponse 抽象
│   ├── openai_provider.py  OpenAI 兼容协议翻译
│   ├── anthropic_provider.py  Anthropic Claude 协议翻译
│   └── factory.py     工厂函数: make_llm(cfg)
├── agent/
│   ├── loop.py        核心 ReAct 循环
│   ├── messages.py    消息历史管理 + 截断
│   └── prompts.py     系统提示词
└── tools/
    ├── base.py        Tool 抽象类
    ├── registry.py    ToolRegistry + 默认工具装配
    ├── fs.py          文件系统工具 (read/write/edit/list)
    ├── search.py      搜索工具 (grep/glob)
    └── shell.py       命令执行工具

tests/
├── test_llm.py       LLM 抽象层翻译测试 (10 个)
├── test_tools.py      工具层测试 (18 个)
├── test_loop.py       Agent Loop 测试 (9 个)
└── test_anthropic.py  Anthropic provider 测试 (12 个)
```

## 命令行选项

```
usage: swe-agent [-h] [--version] [--check] [--task TASK]
                 [--workspace WORKSPACE] [--max-steps MAX_STEPS]

Minimal SWE Agent — 一个学习用的 ReAct 软件工程智能体。

options:
  -h, --help            显示帮助
  --version             显示版本号
  --check               只检查配置不启动
  --task TASK           直接执行任务 (非交互模式)
  --workspace WORKSPACE 工作目录 (默认 .)
  --max-steps MAX_STEPS 最大步数 (默认来自 .env)
```

### REPL 斜杠命令

| 命令 | 作用 |
|---|---|
| `/help` | 显示帮助 |
| `/model` | 查看当前模型配置 |
| `/config` | 查看完整配置 |
| `/tokens` | 查看累计 token 用量 |
| `/q` `/quit` | 退出 |

## 环境变量

参见 [.env.example](.env.example)。支持：

| 变量 | 说明 |
|---|---|
| `LLM_PROVIDER` | `openai` 或 `anthropic` |
| `OPENAI_API_KEY` | OpenAI 兼容 API key |
| `OPENAI_BASE_URL` | API 地址 (可换 DeepSeek/Qwen 等) |
| `OPENAI_MODEL` | 模型名 |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_MODEL` | Claude 模型名 |
| `MAX_STEPS` | 最大 ReAct 步数 (默认 30) |

## 学习路线

这个项目分 6 个阶段构建，每个阶段都有明确的学习目标：

| 阶段 | 内容 | 学到什么 |
|---|---|---|
| 0 | 项目骨架 | Python 项目结构、pyproject.toml、模块组织 |
| 1 | LLM 抽象层 | 协议抽象、Provider 模式、OpenAI API 翻译 |
| 2 | 工具层 | 工具注册模式、路径安全、精确编辑算法 |
| 3 | **Agent Loop ★** | **ReAct 循环、Callback 模式、消息截断** |
| 4 | Anthropic provider | 验证抽象层正确性、多 Provider 支持 |
| 5 | CLI 打磨 | REPL、斜杠命令、彩色输出、跨任务统计 |
| 6 | README + Demo | 文档、mock 演示、最终验收 |

每个阶段的完整代码都在仓库中，你可以在 Git 历史中追溯每个阶段的增量。

### 关键设计决策

- **EditFileTool 用唯一字符串匹配**：不依赖行号（行号会随修改变化），用唯一上下文字符串定位。匹配失败会返回明确错误，迫使 LLM 提供足够上下文。这是 Aider、Claude Code 等行业工具的实践做法。
- **路径遍历防护**：所有文件工具在工作目录下解析路径，通过 `_resolve()` 检查 escape 尝试。
- **ScriptedLLM 测试模式**：用预设剧本替代真实 LLM，实现对 Agent Loop 所有路径的确定性测试——正常完成、工具链、错误恢复、步数上限、LLM 故障。

## 许可证

MIT
