"""
Prompt 模板端口 — 定义领域层与 Prompt 管理系统之间的契约。

基础设施层（LangChain ChatPromptTemplate + YAML 加载器）实现此 Protocol。
领域层只依赖此接口，不感知 LangChain 的 ChatPromptTemplate。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class PromptTemplate:
    """领域层 Prompt 模板 — 与 LangChain ChatPromptTemplate 解耦。"""

    name: str
    """模板名称（如 writer / auditor / character_extractor）。"""

    description: str = ""
    """模板用途说明。"""

    system_prompt: str = ""
    """System Prompt 模板（支持 {variable} 占位符）。"""

    human_prompt: str = ""
    """Human Prompt 模板（支持 {variable} 占位符）。"""

    variables: list[str] = field(default_factory=list)
    """模板中使用的所有变量名。用于验证和文档生成。"""


@dataclass
class RenderedPrompt:
    """渲染后的 Prompt — 准备发送给 LLM 的消息列表。"""

    messages: list[dict[str, str]]
    """渲染后的消息列表 [{"role": "system", "content": "..."}, ...]。"""

    token_estimate: int = 0
    """渲染后内容的 Token 估算。"""


class PromptTemplateProtocol(Protocol):
    """Prompt 模板端口 — 模板加载 + 变量渲染。

    基础设施层实现示例：
        from langchain_core.prompts import ChatPromptTemplate
        class LangChainPromptManager: ...

    测试时可注入 Mock 实现，不依赖 YAML 文件。
    """

    def load(self, template_name: str) -> PromptTemplate:
        """从仓库加载 Prompt 模板。

        Args:
            template_name: 模板名称（不含扩展名）。

        Returns:
            解析后的 PromptTemplate。

        Raises:
            TemplateNotFoundError: 模板不存在。
        """
        ...

    def render(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> RenderedPrompt:
        """渲染模板，将变量值填入占位符。

        Args:
            template: Prompt 模板。
            variables: 变量名 → 变量值映射。

        Returns:
            渲染后的消息列表。

        Raises:
            TemplateRenderError: 缺少必需变量或渲染失败。
        """
        ...

    def list_templates(self) -> list[str]:
        """列出所有可用模板名称。"""
        ...

    def validate(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> list[str]:
        """验证变量是否满足模板要求。

        Args:
            template: Prompt 模板。
            variables: 提供的变量映射。

        Returns:
            缺失变量的名称列表。空列表 = 验证通过。
        """
        ...
