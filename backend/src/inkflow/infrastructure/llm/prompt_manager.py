"""LangChain Prompt 模板管理器 — YAML 模板 + 变量渲染。

领域层通过 PromptTemplateProtocol 调用，不感知 LangChain。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from inkflow.domain.ports.llm_errors import TemplateNotFoundError, TemplateRenderError
from inkflow.domain.ports.prompt_template import PromptTemplate, RenderedPrompt
from inkflow.i18n.resolver import resolve_locale


class LangChainPromptManager:
    """YAML Prompt 模板管理器。

    Args:
        templates_dir: YAML 模板存储目录路径（扁平模式，locale 无关）。
            None 时使用包内 per-locale 模板根 ``inkflow/i18n/prompts/<locale>/``，
            locale 由 ``resolve_locale()`` 每次调用实时解析。
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self._prompts_root: Path | None
        self._templates_dir: Path | None
        if templates_dir is None:
            import inkflow.i18n as i18n_pkg

            self._prompts_root = Path(i18n_pkg.__file__).resolve().parent / "prompts"
            self._templates_dir = None
        else:
            self._prompts_root = None
            self._templates_dir = Path(templates_dir)
            self._templates_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──

    def load(self, template_name: str, locale: str | None = None) -> PromptTemplate:
        """从 YAML 文件加载 Prompt 模板。

        扁平模式（构造时显式传 templates_dir）：locale 被忽略，读
        ``<templates_dir>/<name>.yaml``。per-locale 模式：按
        ``resolve_locale(locale)`` 读 ``i18n/prompts/<locale>/<name>.yaml``；
        目标 locale 文件缺失时回退 ``zh``，仍缺失则抛 TemplateNotFoundError。
        """
        path = self._template_path(template_name, locale)
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

    def list_templates(self, locale: str | None = None) -> list[str]:
        """列出可用模板名称（不含扩展名）。

        扁平模式列出 ``templates_dir/*.yaml``；per-locale 模式列出
        ``prompts/<resolve_locale(locale)>/*.yaml``。
        """
        base = self._resolve_dir(locale)
        if base is None or not base.is_dir():
            return []
        return sorted(path.stem for path in base.glob("*.yaml"))

    def validate(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> list[str]:
        """验证变量是否满足模板要求。返回缺失变量名列表。"""
        return [v for v in template.variables if v not in variables]

    # ── Private helpers ──

    def _resolve_dir(self, locale: str | None) -> Path | None:
        """返回当前模式下的模板目录（per-locale 时按 locale 解析）。"""
        if self._templates_dir is not None:
            return self._templates_dir
        assert self._prompts_root is not None
        return self._prompts_root / resolve_locale(locale)

    def _template_path(self, name: str, locale: str | None = None) -> Path:
        """定位模板文件；per-locale 模式下目标文件缺失时回退 zh。"""
        base = self._resolve_dir(locale)
        if self._templates_dir is not None:
            assert base is not None
            return base / f"{name}.yaml"
        assert base is not None
        path = base / f"{name}.yaml"
        if not path.exists() and resolve_locale(locale) != "zh":
            assert self._prompts_root is not None
            fallback = self._prompts_root / "zh" / f"{name}.yaml"
            if fallback.exists():
                return fallback
        return path

    @staticmethod
    def _format(template_str: str, variables: dict[str, str]) -> str:
        """使用字符串替换渲染模板（安全，避免 KeyError）。"""
        result = template_str
        for key, value in variables.items():
            result = result.replace("{" + key + "}", str(value))
        return result
