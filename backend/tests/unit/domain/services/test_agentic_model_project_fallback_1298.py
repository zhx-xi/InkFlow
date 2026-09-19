"""#1298 RED 契约：agentic 轨模型解析须回退项目 config.model。

背景（2026-09-19 v0.15.0-rc3 旅程实测）：
  项目 config.model = 'deepseek/deepseek-flash'，全局 config.llm_default_model = ''
  → /settings/model-readiness 报 ready=true
  → 但 agentic 装配 `resolve_llm_credentials(config.llm_default_model)` 单参调用
    → fail-fast 422「未配置默认模型」

解析链应为（与 book 轨 books.py:375-378 / chapter_audit 同源）：
  项目 config.model  >  全局 config.llm_default_model  >  fail-fast

🔴 结构约束（父侧实测，决定 422 落点）：
  `get_agentic_writer_service` 是 FastAPI `Depends` → **在 endpoint 函数体之前解析**。
  若装配期就 fail-fast，全局为空时 `run()` 永不可达 → 项目级回退失效（本文件
  `TestAssemblyDoesNotFailFastTooEarly` 即钉住这一条）。
  故 422 必须落在 `_agent_factory`（run 内、同一入口、仍零注册表扫描）。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from inkflow.api import deps_agentic_writer as daw
from inkflow.domain.models.agent_run import AgenticWriteRequest
from inkflow.domain.services.agentic_writer_service import AgenticWriterService

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
CHAPTER_ID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
PROJECT_MODEL = "deepseek/deepseek-flash"
GLOBAL_MODEL = "openai/gpt-4o-mini"


def _request() -> AgenticWriteRequest:
    return AgenticWriteRequest(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, outline="本章大纲")


class _Cfg:
    """项目配置鸭子类型（`_config_value` 支持 .config.<key> 形态）。"""

    def __init__(self, model: str | None) -> None:
        self.config = MagicMock(model=model, writing_style=None, reasoning_effort=None)


def _agent() -> MagicMock:
    a = MagicMock()
    a.invoke = AsyncMock(return_value={"messages": []})
    return a


def _service(project_config: object | None, factory) -> AgenticWriterService:
    """最小可 run 的 service。

    🔴 `run_repo` 必须 AsyncMock —— `run()` 先 `await run_repo.create`，
    MagicMock 不可 await（TypeError），夹具会假红。
    """
    return AgenticWriterService(
        agent_factory=factory,
        draft_service=MagicMock(),
        # 🔴 audit / run_repo 均被 await（`_audit` → record；`run` → create/save）——
        # 必须 AsyncMock，MagicMock 不可 await（TypeError）会假红。
        audit_service=AsyncMock(),
        run_repo=AsyncMock(),
        chapter_service=None,
        project_config_getter=AsyncMock(return_value=project_config),
    )


class TestProjectModelFallback:
    """项目 config.model 有值 + 全局空 → 不得报未配置模型。"""

    def test_agent_factory_receives_project_model_when_global_empty(self) -> None:
        """① 项目级回退：解析到项目模型，且传给 agent_factory。"""
        seen: dict[str, object] = {}
        svc = _service(
            _Cfg(PROJECT_MODEL),
            lambda request, model=None: (seen.update(model=model), _agent())[1],
        )
        with patch("inkflow.core.config.config") as m_cfg:
            m_cfg.llm_default_model = ""
            m_cfg.llm_reasoning_effort = None
            asyncio.run(svc.run(_request()))

        assert seen.get("model") == PROJECT_MODEL, (
            f"项目 config.model 应回退生效，实际 model={seen.get('model')!r}"
        )

    def test_global_still_works_when_project_model_empty(self) -> None:
        """② 全局仍可用：项目模型空 + 全局有值 → 用全局。"""
        seen: dict[str, object] = {}
        svc = _service(
            _Cfg(None),
            lambda request, model=None: (seen.update(model=model), _agent())[1],
        )
        with patch("inkflow.core.config.config") as m_cfg:
            m_cfg.llm_default_model = GLOBAL_MODEL
            m_cfg.llm_reasoning_effort = None
            asyncio.run(svc.run(_request()))

        assert seen.get("model") == GLOBAL_MODEL

    def test_both_empty_raises_422_at_factory_not_silent(self) -> None:
        """③ 都为空才 fail：两者皆空 → 工厂内 fail-fast 422（禁静默放行）。

        422 落在 `_agent_factory` 内（run 内同一入口），非 domain 自抛 ——
        domain 抛非 NotFound 异常会被 `writing.py:88` 改写成 500。
        """
        from inkflow.api._llm_resolver import resolve_llm_credentials

        def _factory(request: object, model: str | None = None) -> object:
            if not model:
                # 装配层同一入口（零注册表扫描，镜像 #929 契约）
                resolve_llm_credentials("", project_model=None)
            return _agent()

        svc = _service(_Cfg(None), _factory)
        with patch("inkflow.core.config.config") as m_cfg:
            m_cfg.llm_default_model = ""
            m_cfg.llm_reasoning_effort = None
            m_cfg.model_routing = {}
            with patch("inkflow.infrastructure.llm.provider_config.get_provider_config") as m_gp:
                m_gp.side_effect = ValueError("API key not configured for provider")
                with pytest.raises(HTTPException) as exc:
                    asyncio.run(svc.run(_request()))

        assert exc.value.status_code == 422
        assert "未配置默认模型" in str(exc.value.detail)
        assert m_gp.call_count == 0, "#929: 空默认绝不遍历注册表"


class TestReadinessConsistency:
    """⑤ 与 model-readiness 口径一致。"""

    def test_ready_project_does_not_warn_unconfigured(self) -> None:
        """readiness 判 ready 的项目（项目 config.model 有值）→ 解析器不抛 422。

        readiness 判据 = `resolve_model(None, project_model, global_default)`（#1129）。
        """
        from inkflow.api._llm_resolver import resolve_chat_model

        with patch("inkflow.core.config.config") as m_cfg:
            m_cfg.llm_default_model = ""
            m_cfg.model_routing = {}
            with patch("inkflow.infrastructure.llm.provider_config.get_provider_config") as m_gp:
                m_gp.return_value = MagicMock(api_key="k", base_url="")
                model = resolve_chat_model("", project_model=PROJECT_MODEL)

        assert model == PROJECT_MODEL


class TestAssemblyDoesNotFailFastTooEarly:
    """🔴 决定本轨是否真修好的结构护栏。

    `get_agentic_writer_service` 是 FastAPI Depends，先于 endpoint 函数体解析 ——
    若装配期在「全局为空」时就抛 422，run() 永不可达，项目级回退永久失效。
    """

    def test_assembly_survives_empty_global_so_run_is_reachable(self) -> None:
        from inkflow.core.config import config

        m_writer = MagicMock()
        with (
            patch.object(config, "llm_default_model", ""),
            patch.object(config, "llm_reasoning_effort", None),
            patch("inkflow.api.deps.get_character_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_foreshadowing_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_summary_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_chapter_audit_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_world_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_draft_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_audit_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_memory_service", return_value=MagicMock()),
            patch("inkflow.api.deps.get_chapter_service", return_value=MagicMock()),
            patch("inkflow.api.deps._make_draft_volume_lookup", return_value=None),
            patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer", m_writer),
        ):
            try:
                svc = daw.get_agentic_writer_service(db=AsyncMock())
            except HTTPException as exc:
                pytest.fail(
                    "装配期在全局为空时 fail-fast → run() 不可达，项目级回退永久失效"
                    f"（#1298 核心缺陷）。实际: 422 {exc.detail}"
                )
            assert svc is not None

    def test_agentic_deps_has_no_single_arg_resolve(self) -> None:
        """装配层不得单参调用（丢失项目级回退）。"""
        src = inspect.getsource(daw)
        assert "resolve_llm_credentials(\n        config.llm_default_model\n    )" not in src, (
            "agentic 装配不得单参调用 resolve_llm_credentials（丢失项目级回退）"
        )
