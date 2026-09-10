"""#936 B 项 RED 契约：显式 embedding 误配类型校验。

缺陷背景（评审 MINOR-3，issue #936 B 项）：
`_llm_resolver.py:33-48` —— 用户**显式**配置 `default.model=zhipu/embedding-3`
（或项目 config.model 选错）→ 解析链全程不看 type 原样接受 → 同款 zhipu 400 1213
「未正常接收到prompt参数」。#929 封死的是「系统静默误捡」，
「用户显式误配」未罩。

契约（#936 spec §3.2）：
① resolver 中 named model 若能在注册表查到且 `type == "embedding"` → **422**
   + ERROR 日志锚「LLM 模型解析失败（类型不符）」；
② **注册表查不到 type（自定义 provider / 手工 config.json）→ 放行**（误伤防御）；
③ 注册表查询异常 → 放行（探针语义，镜像 resolve_reasoning_manual 先例）；
④ 422 detail 用**新锚文本**（不复用旧 detail）——两类错误（未配置 vs 类型不符）
   必须可区分，且旧 detail 在 test_llm_resolver_929.py:81 有精确相等断言。

【R】= 当前必 FAIL（修复锚）；【G】= 当前 PASS（回归守护）。
patch seam（#758 判别法）：被测符号为**函数级 import 的源模块属性**——
`get_provider_config` / `_await_registry_entry` 均在
`inkflow.infrastructure.llm.provider_config` 定义（resolver 内函数级 import），
故一律 patch **源模块**属性（不是 inkflow.api._llm_resolver）。
"""

from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException
from loguru import logger

MODEL_EMB = "zhipu/embedding-3"
MODEL_CHAT = "deepseek/deepseek-v4-flash"

TYPE_MISMATCH_ANCHOR = "LLM 模型解析失败（类型不符）"
RESOLVE_422_DETAIL = "未配置默认模型，请在设置中配置 LLM Provider 和默认模型"


@pytest.fixture(autouse=True)
def _restore_loguru():
    """还原 loguru 全局 sink（镜像 test_llm_resolver_929 模式）。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_logs(level: str = "DEBUG"):
    """捕获 loguru 记录。"""
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _error_logs(records: list) -> list[str]:
    """提取 ERROR 级日志文本。"""
    return [str(r["message"]) for r in records if r["level"].name == "ERROR"]


def _provider_cfg(provider: str, api_key: str = "k-test") -> object:
    """构造 LLMProviderConfig 替身（真实 dataclass，字段与生产一致）。"""
    from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

    return LLMProviderConfig(
        provider=provider,
        api_key=api_key,
        base_url="https://example.test/v1",
        default_model="",
        models=[],
    )


def _registry_entry(provider: str, models: list) -> object:
    """构造注册表条目替身（ProviderConfig 的真实形态，含 models[].type）。"""
    from inkflow.domain.models.provider_config import ProviderConfig

    return ProviderConfig(id=1, name=provider, models=models)


class TestExplicitEmbeddingMisconfig:
    """契约①：显式配 embedding 模型当 chat → 422 + 类型锚。"""

    def test_r1_embedding_type_raises_422_with_anchor(self) -> None:
        """【R】named model 查到 type=embedding → 422 + ERROR 锚「类型不符」。

        RED 形态：当前无类型校验 → 返回三元组（DID NOT RAISE）。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.domain.models.provider_config import ProviderModel

        registry = _registry_entry("zhipu", [ProviderModel(id="embedding-3", type="embedding")])

        records, sid = _capture_logs()
        try:
            with (
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    return_value=_provider_cfg("zhipu"),
                ),
                patch(
                    "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                    return_value=registry,
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                resolve_llm_credentials(MODEL_EMB)
        finally:
            logger.remove(sid)

        assert exc_info.value.status_code == 422
        assert any(TYPE_MISMATCH_ANCHOR in msg for msg in _error_logs(records)), (
            f"#936 B 项：类型不符须落 ERROR 锚={TYPE_MISMATCH_ANCHOR!r}，"
            f"实际 {_error_logs(records)}"
        )

    def test_r2_new_detail_distinct_from_not_configured(self) -> None:
        """【R】类型不符 detail 与「未配置」detail **不同**（两类错误可区分）。

        旧 detail（#821/#929 契约，test_llm_resolver_929.py:81 精确断言）
        必须原样保留给「未配置」；类型不符用新文案。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.domain.models.provider_config import ProviderModel

        registry = _registry_entry("zhipu", [ProviderModel(id="embedding-3", type="embedding")])

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("zhipu"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                return_value=registry,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            resolve_llm_credentials(MODEL_EMB)

        detail = exc_info.value.detail
        assert detail != RESOLVE_422_DETAIL, (
            "类型不符须用新 detail——两类错误应可区分（且不破坏 #821 契约的精确断言）"
        )
        assert "embedding" in detail, f"detail 应含模型类型信息，实际 {detail!r}"
        assert "embedding-3" in detail, f"detail 应含模型 id，实际 {detail!r}"

    def test_r3_project_model_misconfig_also_caught(self) -> None:
        """【R】project_model 误配 embedding → 同样 422（Q1 拍板）。

        项目级误配与全局误配同款风险——`resolve_model` 结果统一校验。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.domain.models.provider_config import ProviderModel

        registry = _registry_entry("zhipu", [ProviderModel(id="embedding-3", type="embedding")])

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("zhipu"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                return_value=registry,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            resolve_llm_credentials("", project_model=MODEL_EMB)

        assert exc_info.value.status_code == 422


class TestTypeCheckPassThrough:
    """契约②③：放行路径（误伤防御）——不得因类型校验破坏既有可用场景。"""

    def test_r4_unknown_type_passes_through(self) -> None:
        """【R】注册表查不到该模型条目 → **放行**（自定义 provider/手工 config.json）。

        RED 形态：当前无校验也放行（PASS）；实现后若写成「查不到即拒绝」→ 翻红。
        这是给实现方的**误伤防御锚**：只有确知 type=embedding 才拒绝。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.domain.models.provider_config import ProviderModel

        # 注册表有其他模型，但不含请求的 embedding-3
        registry = _registry_entry("zhipu", [ProviderModel(id="glm-4.5", type="chat")])

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("zhipu"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                return_value=registry,
            ),
        ):
            model, api_key, _ = resolve_llm_credentials(MODEL_EMB)

        assert model == MODEL_EMB, "注册表无该条目 = type 未知 → 必须放行（误伤防御）"
        assert api_key == "k-test"

    def test_r5_registry_lookup_failure_passes_through(self) -> None:
        """【R】注册表查询异常 → **放行**（探针语义：查询失败绝不冒泡）。

        镜像 resolve_reasoning_manual 先例（provider_config.py:166-173）：
        查询失败 → None（跟随），绝不因辅助信息查询失败阻断主路径。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("zhipu"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                side_effect=RuntimeError("DB not initialised"),
            ),
        ):
            model, _, _ = resolve_llm_credentials(MODEL_EMB)

        assert model == MODEL_EMB, "注册表查询异常不得阻断主路径（放行）"

    def test_r6_registry_none_passes_through(self) -> None:
        """【R】注册表返回 None（无该 provider）→ 放行。"""
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("zhipu"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                return_value=None,
            ),
        ):
            model, _, _ = resolve_llm_credentials(MODEL_EMB)

        assert model == MODEL_EMB


class TestChatTypeGuard:
    """【G】护栏：chat 型 named model 正常放行（防过度修正）。"""

    def test_g1_chat_type_passes_with_triple(self) -> None:
        """【G】注册表查到 type=chat → 正常返回三元组。"""
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.domain.models.provider_config import ProviderModel

        registry = _registry_entry(
            "deepseek", [ProviderModel(id="deepseek-v4-flash", type="chat")]
        )

        with (
            patch(
                "inkflow.infrastructure.llm.provider_config.get_provider_config",
                return_value=_provider_cfg("deepseek", api_key="k-ds"),
            ),
            patch(
                "inkflow.infrastructure.llm.provider_config._await_registry_entry",
                return_value=registry,
            ),
        ):
            model, api_key, base_url = resolve_llm_credentials(MODEL_CHAT)

        assert model == MODEL_CHAT
        assert api_key == "k-ds"
        assert base_url == "https://example.test/v1"

    def test_g2_empty_default_still_uses_old_detail(self) -> None:
        """【G】护栏：「未配置」路径 detail 逐字不变（#821/#929 契约零破坏）。"""
        from inkflow.api._llm_resolver import resolve_llm_credentials

        with pytest.raises(HTTPException) as exc_info:
            resolve_llm_credentials("")

        assert exc_info.value.detail == RESOLVE_422_DETAIL, (
            "护栏：未配置类错误的 detail 必须逐字保留（test_llm_resolver_929.py:81 精确断言）"
        )
