"""F59-M2 RED (#963): 思考档位领域层契约 — ReasoningEffort 枚举 + 配置字段 + 解析链。

契约（spec v1.2 §2.1/§2.2/§4 + issue #963 范围 1-4/9）:
1. ``domain/models/reasoning.py`` 导出 ``ReasoningEffort`` 七档 Literal
   （none/minimal/low/medium/high/xhigh/default，对齐 litellm 签名）与
   ``REASONING_EFFORTS`` 元组；domain 层零 litellm import（§5.6 依赖方向）。
2. ``ProjectConfig.reasoning_effort: ReasoningEffort | None``，默认 None=跟随全局；
   旧 config JSON 无键 → None（零迁移）；非法档位 → ValidationError。
3. ``InkFlowConfig.llm_reasoning_effort`` 默认 ``"default"``；
   ``CONFIG_WHITELIST["default.reasoning_effort"] == "llm_reasoning_effort"``
   （CLI ``config set default.reasoning_effort high`` 自动可用，§4）。
4. ``resolve_reasoning_effort(request_effort, project_effort, global_effort)``：
   调用 > 项目 > 全局，**首个非 None 即用**（"default"/"none" 是显式值参与优先级，
   不被 falsy 跳过）；全 None → "default" 兜底。
5. i18n 目录登记：``api.error.reasoning_effort_invalid`` /
   ``log.check.reasoning_downgrade``（zh/en 双备，F57 对称性契约联动
   test_logging_message_keys）。

RED 预期失败形态:
- ``inkflow.domain.models.reasoning`` 不存在 → 收集期 ModuleNotFoundError。
- ProjectConfig/InkFlowConfig 无字段 → AttributeError/KeyError/AssertionError。
- resolve_reasoning_effort 不存在 → ImportError。
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from inkflow.core.config import CONFIG_WHITELIST, InkFlowConfig
from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.models.reasoning import REASONING_EFFORTS, ReasoningEffort
from inkflow.domain.services.model_resolution import resolve_reasoning_effort

EXPECTED_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "default"}


class TestReasoningEffortLiteral:
    """§2.1：七档 Literal + 常量表，domain 零 litellm。"""

    def test_seven_levels(self) -> None:
        """REASONING_EFFORTS 恰含 litellm 七档（不多不少）。"""
        assert set(REASONING_EFFORTS) == EXPECTED_EFFORTS

    def test_typing_literal_values(self) -> None:
        """ReasoningEffort 本身是 Literal[...]，args 即七档（英文档名不进 i18n 值域）。"""
        # typing.Literal 的 args 为值元组
        assert set(ReasoningEffort.__args__) == EXPECTED_EFFORTS

    def test_domain_module_free_of_litellm(self) -> None:
        """§5.6 依赖方向：domain/models/reasoning.py 源码零 litellm 引用。"""
        src = inspect.getsource(inspect.getmodule(ReasoningEffort) or inspect)
        assert "litellm" not in src


class TestProjectConfigReasoning:
    """§2.2 行 2：ProjectConfig.reasoning_effort（None=跟随全局，零迁移）。"""

    def test_default_none(self) -> None:
        assert ProjectConfig().reasoning_effort is None

    def test_legacy_json_without_key_deserializes_none(self) -> None:
        """旧 config JSON（无该键）model_validate → None（零迁移语义）。"""
        cfg = ProjectConfig.model_validate({"model": "deepseek/deepseek-chat"})
        assert cfg.reasoning_effort is None

    def test_valid_level_roundtrip(self) -> None:
        cfg = ProjectConfig(reasoning_effort="high")
        assert cfg.reasoning_effort == "high"
        assert cfg.model_dump()["reasoning_effort"] == "high"

    def test_invalid_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(reasoning_effort="ultra")

    def test_none_explicit_allowed(self) -> None:
        """显式 null（PATCH 清除项目档位 → 回落全局）必须合法。"""
        cfg = ProjectConfig.model_validate({"reasoning_effort": None})
        assert cfg.reasoning_effort is None


class TestGlobalConfigField:
    """§2.2 行 1 + §4：llm_reasoning_effort 默认 "default" + CLI 白名单键。"""

    def test_field_default_is_default_level(self) -> None:
        assert InkFlowConfig.model_fields["llm_reasoning_effort"].default == "default"

    def test_whitelist_key(self) -> None:
        assert CONFIG_WHITELIST.get("default.reasoning_effort") == "llm_reasoning_effort"

    def test_invalid_value_rejected_by_model_validate(self) -> None:
        """CLI 路径复用 model_validate（config_cmd 白名单后统一校验）。"""
        with pytest.raises(ValidationError):
            InkFlowConfig.model_validate({"llm_reasoning_effort": "bogus"})

    def test_valid_value_accepted(self) -> None:
        cfg = InkFlowConfig.model_validate({"llm_reasoning_effort": "medium"})
        assert cfg.llm_reasoning_effort == "medium"


class TestResolveReasoningEffort:
    """§2.2 解析优先级链：调用 > 项目 > 全局，首个非 None 即用。"""

    def test_request_wins(self) -> None:
        assert (
            resolve_reasoning_effort(
                request_effort="low", project_effort="high", global_effort="medium"
            )
            == "low"
        )

    def test_project_when_request_none(self) -> None:
        assert (
            resolve_reasoning_effort(
                request_effort=None, project_effort="high", global_effort="medium"
            )
            == "high"
        )

    def test_global_when_request_and_project_none(self) -> None:
        assert (
            resolve_reasoning_effort(
                request_effort=None, project_effort=None, global_effort="medium"
            )
            == "medium"
        )

    def test_all_none_falls_back_to_default(self) -> None:
        """全 None → "default"（不发任何思考参数，等价现状）。"""
        assert (
            resolve_reasoning_effort(request_effort=None, project_effort=None, global_effort=None)
            == "default"
        )

    def test_explicit_default_at_request_overrides_project(self) -> None:
        """🔴 "default" 是显式档位（用户主动选「跟随模型默认」），不被 falsy 跳过。"""
        assert (
            resolve_reasoning_effort(
                request_effort="default", project_effort="high", global_effort="high"
            )
            == "default"
        )

    def test_explicit_none_level_overrides_project(self) -> None:
        """"none"（显式关闭）同样是值：区别于 None（未配置=跟随上级）。"""
        assert (
            resolve_reasoning_effort(request_effort="none", project_effort="high", global_effort=None)
            == "none"
        )

    def test_signature_is_keyword_friendly(self) -> None:
        """纯函数（同 resolve_model 形态）：无副作用，位置参亦可。"""
        assert resolve_reasoning_effort(None, None, "low") == "low"


class TestProviderModelSupportsReasoning:
    """§2.2 行 4：ProviderModel.supports_reasoning（bool|None 三态，None=自动探测）。

    models 存 JSON 列（repo 层 model_dump/validate 往返）→ 加字段零迁移。
    """

    def test_default_none_auto_probe(self) -> None:
        from inkflow.domain.models.provider_config import ProviderModel

        m = ProviderModel(id="glm-4.5", type="chat")
        assert m.supports_reasoning is None

    def test_manual_true_false_roundtrip(self) -> None:
        from inkflow.domain.models.provider_config import ProviderModel

        assert ProviderModel(id="a", type="chat", supports_reasoning=True).supports_reasoning is True
        assert ProviderModel(id="b", type="chat", supports_reasoning=False).supports_reasoning is False
        # JSON 列往返（repo _to_domain 形态）
        dumped = ProviderModel(id="c", type="chat", supports_reasoning=False).model_dump()
        assert dumped["supports_reasoning"] is False
        assert ProviderModel.model_validate(dumped).supports_reasoning is False

    def test_legacy_json_without_key_deserializes_none(self) -> None:
        """旧注册表 JSON（无键）→ None（零迁移）。"""
        from inkflow.domain.models.provider_config import ProviderModel

        m = ProviderModel.model_validate({"id": "old", "type": "chat", "roles": []})
        assert m.supports_reasoning is None


class TestReasoningI18nMessages:
    """§8.2 i18n 行：422 文案 + 降级 WARNING message_key 双语言目录登记。"""

    @pytest.mark.parametrize("locale", ["zh", "en"])
    def test_keys_registered(self, locale: str) -> None:
        from inkflow.i18n.resolver import load_messages

        msgs = load_messages("messages", locale)
        assert "api.error.reasoning_effort_invalid" in msgs, f"{locale} 缺 422 文案键"
        assert "log.check.reasoning_downgrade" in msgs, f"{locale} 缺降级 WARNING 键"
        # 占位符契约：params 携带 model/effort（实现方必须以此二键传参）
        tmpl = msgs["log.check.reasoning_downgrade"]
        assert "{model}" in tmpl and "{effort}" in tmpl, f"降级文案缺占位符：{tmpl}"
        assert msgs["api.error.reasoning_effort_invalid"].strip()
