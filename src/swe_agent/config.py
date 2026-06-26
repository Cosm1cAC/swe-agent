"""配置加载: 从环境变量/.env 读取所有运行参数。

为什么单独抽一个 config 模块?
  - 让 LLM 层、工具层、agent loop 都不直接碰 os.environ,
    而是依赖一个类型明确的 Config 对象 —— 便于测试和替换。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# 加载 .env 到环境变量 (找不到 .env 时静默跳过)
load_dotenv()


def _get(key: str, default: str = "") -> str:
    """从环境变量取值, 缺省返回 default。"""
    return os.environ.get(key, default)


def _get_int(key: str, default: int) -> int:
    """取整数, 解析失败回退到 default。"""
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    """全局配置。各模块从这里读它需要的字段。"""

    # ── LLM provider 选择 ──────────────────────────────────────
    provider: str = field(default_factory=lambda: _get("LLM_PROVIDER", "openai").lower())

    # ── OpenAI 兼容 (DeepSeek/Qwen/Groq/智谱 等共用此组) ─────────
    openai_api_key: str = field(default_factory=lambda: _get("OPENAI_API_KEY"))
    openai_base_url: str = field(
        default_factory=lambda: _get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    openai_model: str = field(default_factory=lambda: _get("OPENAI_MODEL", "gpt-4o-mini"))

    # ── Anthropic Claude ────────────────────────────────────────
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(
        default_factory=lambda: _get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    )

    # ── Agent 行为 ──────────────────────────────────────────────
    max_steps: int = field(default_factory=lambda: _get_int("MAX_STEPS", 30))

    def validate(self) -> list[str]:
        """检查关键配置是否齐全, 返回问题列表 (空列表 = OK)。"""
        problems: list[str] = []
        if self.provider == "openai":
            if not self.openai_api_key:
                problems.append("OPENAI_API_KEY 未设置 (见 .env.example)")
        elif self.provider == "anthropic":
            if not self.anthropic_api_key:
                problems.append("ANTHROPIC_API_KEY 未设置 (见 .env.example)")
        else:
            problems.append(f"未知 provider: {self.provider} (应为 openai|anthropic)")
        return problems

    def __repr__(self) -> str:  # 不泄露 key
        return (
            f"Config(provider={self.provider!r}, "
            f"model={self.openai_model if self.provider == 'openai' else self.anthropic_model!r}, "
            f"max_steps={self.max_steps})"
        )


if __name__ == "__main__":
    # 直接运行本文件可快速检查配置是否读对了
    cfg = Config()
    print(cfg)
    problems = cfg.validate()
    if problems:
        print("[!] 配置问题:")
        for p in problems:
            print(f"   - {p}")
    else:
        print("[OK] 配置 OK")
