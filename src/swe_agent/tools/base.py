"""工具基类 + 执行协议。

【设计思路】
  一个工具需要满足两件事:
    1. 告诉 LLM "我是谁、能做什么、要什么参数" —— 用 JSON Schema 描述
    2. 真正被调用时, 接收参数并执行 —— run() 方法

  所以 Tool 基类把这两件事绑成一个对象:
    - schema()  ->  ToolSchema   (给 LLM 看)
    - run(args) ->  str          (执行, 返回文本结果给 LLM 看)

  工具的输入输出统一用 str (给 LLM 的 observation 永远是文本),
  这简化了 loop 的逻辑 —— 它不需要关心不同工具的返回类型。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from swe_agent.llm.base import ToolSchema


class ToolError(Exception):
    """工具执行出错 (如文件不存在、参数缺失)。

    和"程序异常"区分开: ToolError 是可预期的问题,
    会被 loop 捕获后变成给 LLM 的错误信息, 让它有机会自我纠正,
    而不是让整个 agent 崩掉。
    """


@dataclass
class ToolResult:
    """工具执行结果。

    - output:  正常输出文本
    - error:   出错时的错误信息 (二选一: 有 error 则视为失败)
    """

    output: str = ""
    error: str | None = None

    def to_llm_text(self) -> str:
        """转成喂给 LLM 的纯文本 observation。"""
        if self.error is not None:
            return f"[ERROR] {self.error}"
        return self.output


class Tool(ABC):
    """所有工具的基类。子类只需实现三个东西:

      name:        工具名 (LLM 用它来调用)
      description: 一句话描述 (LLM 据此判断何时用)
      parameters_schema(): 参数的 JSON Schema
      run(**args):         实际执行逻辑
    """

    name: str = ""
    description: str = ""

    def schema(self) -> ToolSchema:
        """生成喂给 LLM 的工具描述。"""
        if not self.name:
            raise NotImplementedError(f"{type(self).__name__} 未设置 name")
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema(),
        )

    @abstractmethod
    def parameters_schema(self) -> dict:
        """参数的 JSON Schema。子类实现。"""
        ...

    @abstractmethod
    def run(self, **kwargs) -> ToolResult:
        """执行工具。参数由 LLM 提供 (已从 JSON 解析成 kwargs)。

        出错应抛 ToolError 或返回 ToolResult(error=...), 不要抛裸异常。
        """
        ...

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"
