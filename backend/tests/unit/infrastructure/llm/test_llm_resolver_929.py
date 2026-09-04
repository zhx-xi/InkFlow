"""#929 RED 契约：LLM 模型装配 fail-fast 化（删除静默回退）+ model_routing provider 键值化。

缺陷背景（rc2 实证，issue #929）：全局默认模型为空时 `resolve_llm_credentials`
遍历 provider 注册表取 `models[0]`（不筛 type）→ zhipu 的 embedding-3
（type=embedding）被装配为 chat 模型 → ChatOpenAI 打 chat completions →
zhipu 400 1213「未正常接收到prompt参数」→ book run 全章 failed、tokens=0。
探针实证（.hermes/tmp_repro_c.py，忠实快照 rc2 keys+DB）：
CHAT PROBE(ChatOpenAI model=embedding-3) = BadRequestError 400 1213（同款）。

用户拍板（2026-09-05，契约 .hermes/plans/contract-929.md）：
① model_routing 改 provider 键 → ProviderDefault{model(裸名), type} 值对象；
② 删除最终 fallback——解析不到模型 → logger.error 诊断 + HTTPException 422，
   绝不静默挑一个 provider 的模型；
③ 首启引导 = #934（0.14.0），不进本批。

【R】= 当前必 FAIL（修复锚）；【G】= 当前 PASS（回归守护）。
patch seam（#758 判别法）：get_provider_config / resolve_model 为函数级 import →
patch 源模块属性。
"""

from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException
from loguru import logger

MODEL = "deepseek/deepseek-v4-flash"

RESOLVE_422_DETAIL = "未配置默认模型，请在设置中配置 LLM Provider 和默认模型"
LOG_ANCHOR = "LLM 模型解析失败"


@pytest.fixture(autouse=True)
def _restore_loguru():
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_logs(level: str = "DEBUG"):
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _error_logs(records: list) -> list[str]:
    return [str(r["message"]) for r in records if r["level"].name == "ERROR"]


class TestNoFallbackFailFast:
    """契约②：删除注册表遍历回退——无解 → 422 + 诊断日志，且不扫描任何 provider。"""

    def test_r1_empty_everything_422_without_scanning(self) -> None:
        """【R】project/global 全空 → 422 + 日志含「LLM 模型解析失败」。

        RED 双锚：a) get_provider_config 调用计数 == 0（当前回退循环扫描
        openai/deepseek/zhipu/ollama ≥1 次 → FAIL）；b) 日志锚（当前无该日志 → FAIL）。
        当前 422 本身已抛（全无 key 路径），本契约锁的是「不再扫描 + 有诊断」。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials

        records, sid = _capture_logs()
        try:
            with (
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=ValueError("API key not configured for provider"),
                ) as m_gpc,
                pytest.raises(HTTPException) as exc_info,
            ):
                resolve_llm_credentials("")
        finally:
            logger.remove(sid)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == RESOLVE_422_DETAIL, "422 文案逐字保留（#821 兼容）"
        assert m_gpc.call_count == 0, (
            "#929: 空默认绝不再遍历注册表回退（当前实现扫描 _BUILTIN_PROVIDERS 取 "
            "models[0]，把 embedding 模型装配为 chat——本断言锁死回退删除）"
        )
        assert any(LOG_ANCHOR in msg for msg in _error_logs(records)), (
            f"#929: 解析失败必须落 ERROR 诊断日志（锚={LOG_ANCHOR!r}），实际 {_error_logs(records)}"
        )

    def test_r2_named_provider_key_unavailable_422_queries_only_that_provider(self) -> None:
        """【R】named model 的 provider 无 key → 422，且只查询该 provider 一次。

        RED 形态：当前实现 ValueError 后继续扫描其余 provider（call_count > 1）。
        拍板②：不回退任何其他 provider——错配就是错配，显式失败。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        def _gpc(provider: str, api_key: str | None = None) -> LLMProviderConfig:
            if provider == "deepseek":
                raise ValueError("API key not configured for provider: deepseek")
            # 其他 provider 即使「可用」也不该被查询（回退已删）
            raise AssertionError(f"must not scan other provider: {provider}")

        records, sid = _capture_logs()
        try:
            with (
                patch(
                    "inkflow.infrastructure.llm.provider_config.get_provider_config",
                    side_effect=_gpc,
                ) as m_gpc,
                pytest.raises(HTTPException) as exc_info,
            ):
                resolve_llm_credentials(MODEL)
        finally:
            logger.remove(sid)

        assert exc_info.value.status_code == 422
        assert m_gpc.call_count == 1, (
            "#929: 只允许查询 named model 自己的 provider（deepseek）一次，禁止静默换 provider"
        )
        assert any(LOG_ANCHOR in msg for msg in _error_logs(records))


class TestProjectModelPassthrough:
    """契约 R3/§3：project_model 参数——项目模型 > 全局默认（#735 链进 resolver）。"""

    def test_r3_project_model_resolved(self) -> None:
        """【R】resolve_llm_credentials("", project_model=...) → 项目模型生效。

        RED 形态：当前签名无 project_model 参数 → TypeError。
        """
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        fake = LLMProviderConfig(
            provider="zhipu",
            api_key="k-zhipu",
            base_url="https://example.test/v4/",
            default_model="glm-4.5",
            models=["glm-4.5"],
        )
        with patch(
            "inkflow.infrastructure.llm.provider_config.get_provider_config",
            return_value=fake,
        ):
            model, api_key, base_url = resolve_llm_credentials("", project_model="zhipu/glm-4.5")

        assert model == "zhipu/glm-4.5"
        assert api_key == "k-zhipu"
        assert base_url == "https://example.test/v4/"

    def test_r4_project_model_wins_over_global(self) -> None:
        """【R】project 与 global 同时提供 → 项目模型优先（#735 agent>项目>全局 链）。"""
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        fake = LLMProviderConfig(
            provider="zhipu",
            api_key="k-z",
            base_url="",
            default_model="glm-4.5",
            models=[],
        )
        with patch(
            "inkflow.infrastructure.llm.provider_config.get_provider_config",
            return_value=fake,
        ):
            model, _, _ = resolve_llm_credentials(MODEL, project_model="zhipu/glm-4.5")

        assert model == "zhipu/glm-4.5", "#735：项目级模型必须压过全局默认"


class TestModelRoutingKeyValue:
    """契约①：model_routing 改 provider 键 + {model(裸名), type} 值对象。"""

    def test_r5_provider_keys_and_default_object(self, tmp_path, monkeypatch) -> None:
        """【R】新结构：provider 键（openai/deepseek/zhipu）+ ProviderDefault 值。

        RED 形态：当前 model_routing 键为 task 名（writing/audit/…）→ KeyError。
        """
        monkeypatch.delenv("INKFLOW_MODEL_ROUTING", raising=False)
        from inkflow.core.config import InkFlowConfig
        from inkflow.domain.models.provider_config import ProviderDefault

        cfg = InkFlowConfig(_env_file=None, data_dir=tmp_path)
        assert {"openai", "deepseek", "zhipu"} <= set(cfg.model_routing), (
            f"#929: model_routing 必须以 provider 为键，实际键={sorted(cfg.model_routing)}"
        )
        entry = cfg.model_routing["deepseek"]
        assert isinstance(entry, ProviderDefault)
        assert entry.model == "deepseek-v4-flash", (
            "#415 拍板值保留：deepseek 内置默认 = v4-flash（裸名，不带 provider/ 前缀）"
        )
        assert entry.type == "chat"

    def test_r6_builtin_default_model_helper(self, monkeypatch) -> None:
        """【R】_builtin_default_model(provider)：chat 型 → provider/裸名；embedding/缺键 → ""。

        RED 形态：当前无 _builtin_default_model 函数 → ImportError。
        embedding 型条目永不可作为 chat 内置默认（R1 的结构性防线）。
        """
        from inkflow.core.config import config
        from inkflow.domain.models.provider_config import ProviderDefault
        from inkflow.infrastructure.llm.provider_config import (  # 【R】当前不存在
            _builtin_default_model,
        )

        monkeypatch.setattr(
            config,
            "model_routing",
            {
                "chatp": ProviderDefault(model="c1", type="chat"),
                "emb": ProviderDefault(model="e1", type="embedding"),
            },
            raising=False,
        )
        assert _builtin_default_model("chatp") == "chatp/c1", (
            "消费侧拼 LiteLLM 格式 provider/model（裸名入 value，出参统一格式）"
        )
        assert _builtin_default_model("emb") == "", (
            "#929 核心防线：type=embedding 的内置路由值绝不进入 chat 解析路径"
        )
        assert _builtin_default_model("nope") == ""

    def test_r7_llm_list_reads_model_routing(self) -> None:
        """【R】CLI _PROVIDER_MODELS 硬编码删除（单一默认源 #415 原则）。

        RED 形态：llm.py 仍有模块级 _PROVIDER_MODELS dict（第二份默认值）。
        """
        import inkflow.cli.commands.llm as llm_cli

        assert not hasattr(llm_cli, "_PROVIDER_MODELS"), (
            "#929/§1: llm list 应改读 config.model_routing，"
            "_PROVIDER_MODELS 是第二份默认值（违反 #415 单一默认源原则）"
        )


class TestHappyPathGuard:
    """【G】守护：named model + key 可用 → 正常三元组（零翻转）。"""

    def test_g1_named_model_with_key_returns_triple(self) -> None:
        from unittest.mock import patch

        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        fake = LLMProviderConfig(
            provider="deepseek",
            api_key="test-api-key-value",
            base_url="https://example.test/v1",
            default_model=MODEL,
            models=["deepseek-v4-flash"],
        )
        with patch(
            "inkflow.infrastructure.llm.provider_config.get_provider_config",
            return_value=fake,
        ):
            model, api_key, base_url = resolve_llm_credentials(MODEL)

        assert model == MODEL
        assert api_key == "test-api-key-value"
        assert base_url == "https://example.test/v1"
