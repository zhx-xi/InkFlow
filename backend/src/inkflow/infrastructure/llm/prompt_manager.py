"""LangChain Prompt 模板管理器 — YAML 模板 + 变量渲染。

领域层通过 PromptTemplateProtocol 调用，不感知 LangChain。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from inkflow.domain.ports.llm_errors import TemplateNotFoundError, TemplateRenderError
from inkflow.domain.ports.prompt_template import PromptTemplate, RenderedPrompt


class LangChainPromptManager:
    """YAML Prompt 模板管理器。

    Args:
        templates_dir: YAML 模板存储目录路径。None 时使用包内默认模板目录。
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        if templates_dir is None:
            import inkflow.infrastructure.llm as llm_pkg

            templates_dir = Path(llm_pkg.__file__).parent / "templates"
        self._templates_dir = Path(templates_dir)
        self._templates_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──

    def load(self, template_name: str) -> PromptTemplate:
        """从 YAML 文件加载 Prompt 模板。"""
        path = self._template_path(template_name)
        if not path.exists():
            raise TemplateNotFoundError(template_name)

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise TemplateRenderError(
                f"Failed to parse YAML template: {template_name}: {e}",
                template_name=template_name,
            ) from e

        return PromptTemplate(
            name=data.get("name", template_name),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            human_prompt=data.get("human_prompt", ""),
            variables=data.get("variables", []),
        )

    def render(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> RenderedPrompt:
        """渲染模板变量 → RenderedPrompt。"""
        missing = self.validate(template, variables)
        if missing:
            raise TemplateRenderError(
                f"Missing variables for template {template.name!r}: {missing}",
                template_name=template.name,
                missing_variables=missing,
            )

        messages: list[dict[str, str]] = []
        token_estimate = 0

        if template.system_prompt:
            content = self._format(template.system_prompt, variables)
            messages.append({"role": "system", "content": content})
            token_estimate += len(content) // 4

        if template.human_prompt:
            content = self._format(template.human_prompt, variables)
            messages.append({"role": "user", "content": content})
            token_estimate += len(content) // 4

        return RenderedPrompt(messages=messages, token_estimate=token_estimate)

    def list_templates(self) -> list[str]:
        """列出所有可用模板名称（不含扩展名）。"""
        names: list[str] = []
        for path in self._templates_dir.glob("*.yaml"):
            names.append(path.stem)
        return sorted(names)

    def validate(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> list[str]:
        """验证变量是否满足模板要求。返回缺失变量名列表。"""
        return [v for v in template.variables if v not in variables]

    # ── Private helpers ──

    def _template_path(self, name: str) -> Path:
        return self._templates_dir / f"{name}.yaml"

    @staticmethod
    def _format(template_str: str, variables: dict[str, str]) -> str:
        """使用字符串替换渲染模板（安全，避免 KeyError）。"""
        result = template_str
        for key, value in variables.items():
            result = result.replace("{" + key + "}", str(value))
        return result
