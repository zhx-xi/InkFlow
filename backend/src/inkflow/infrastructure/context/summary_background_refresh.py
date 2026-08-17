"""F45 M2 语义总结后台刷新（#456 第二部分，Q2=B 后半）。

PreferenceSource.background_refresh 的落地实现：fire-and-forget 调度 + 独立
session 后台执行（LLM 调用不占用请求 session/连接）。审计链：
pending_summary（collect 时）→ semantic_summary_generated / semantic_summary_failed。
"""

from __future__ import annotations

import uuid
from typing import cast

from inkflow.domain.models.semantic_summary import SummaryScope


async def run_summary_background_refresh(
    anchors: list,
    *,
    scope: SummaryScope,
    project_id: uuid.UUID | None,
    anchor_hash: str,
    session_factory: object | None = None,
    summarizer: object | None = None,
    summary_repo: object | None = None,
    audit: object | None = None,
) -> bool:
    """后台刷新任务体：独立 session 内 summarize → upsert → 审计（#456）。

    Args:
        anchors: 当前锚点列表（冲突过滤后的 items）.
        scope: 归属范围（project/user）.
        project_id: scope=project 时的项目 UUID；scope=user 时为 None.
        anchor_hash: 当前锚点哈希（spec §5.4）.
        session_factory: async context manager → AsyncSession（测试注入）；
            None → async_session_factory.
        summarizer: summarize(anchors, scope=..., project_id=..., anchor_hash=...,
            model=config.llm_default_model) → (SemanticSummary | None, dropped)
            鸭子对象（测试注入）；None → SemanticSummarizer 真实装配.
        summary_repo: upsert(summary) 鸭子对象（测试注入）；None → 真实 repo.
        audit: record(project_id=..., severity_summary=..., degraded=...,
            actor=..., note=...) 鸭子对象（测试注入）；None → 真实 AuditLogService.

    Returns:
        True=刷新成功落库 / False=失败（LLM 失败/防幻觉丢弃/未预期异常，
        均已审计 semantic_summary_failed，不抛出）。
    """
    from inkflow.core.config import config
    from inkflow.core.database import async_session_factory
    from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError
    from inkflow.domain.services.audit_log_service import AuditLogService
    from inkflow.domain.services.semantic_summarizer import SemanticSummarizer
    from inkflow.infrastructure.database.repositories.audit_log_repo import (
        SQLiteAuditLogRepository,
    )
    from inkflow.infrastructure.database.repositories.semantic_summary_repo import (
        SQLiteSemanticSummaryRepository,
    )
    from inkflow.infrastructure.llm import LangChainLLMClient, LangChainPromptManager

    if session_factory is None:
        session_factory = async_session_factory
    # 兼容双形态：真实默认值为可调用工厂（async_sessionmaker() → AsyncSession）；
    # 测试注入为 async 上下文管理器实例（不可调用）——归一化为上下文管理器对象
    session_cm: object = session_factory() if callable(session_factory) else session_factory
    if summarizer is None:

        def _build_summarizer() -> SemanticSummarizer:
            return SemanticSummarizer(
                llm_client=LangChainLLMClient(),
                prompt_manager=LangChainPromptManager(),
            )

        summarizer = cast(object, _build_summarizer())

    async def _record_failure(note: str) -> None:
        """审计失败（LLM 失败/异常），尽力而为（异常静默旁路，F28 语义）。"""
        try:
            if audit is not None:
                await audit.record(  # type: ignore[attr-defined]  # 鸭子类型：audit 按契约提供 record
                    project_id=project_id,
                    severity_summary="semantic_summary_failed",
                    degraded=True,
                    actor="memory",
                    note=note,
                )
                return
            async with session_cm as session:  # type: ignore[attr-defined]  # 鸭子类型：session_cm 按契约提供 async 上下文
                await AuditLogService(SQLiteAuditLogRepository(session)).record(
                    project_id=project_id,  # type: ignore[arg-type]  # 用户级 scope 为 None（memory L700 先例）
                    severity_summary="semantic_summary_failed",
                    degraded=True,
                    actor="memory",
                    note=note,
                )
        except Exception:
            pass

    try:
        async with session_cm as session:  # type: ignore[attr-defined]  # 鸭子类型：session_cm 按契约提供 async 上下文
            repo: object = (
                summary_repo
                if summary_repo is not None
                else SQLiteSemanticSummaryRepository(session)
            )
            audit_svc: object = (
                audit if audit is not None else AuditLogService(SQLiteAuditLogRepository(session))
            )
            new_summary, dropped = await summarizer.summarize(  # type: ignore[attr-defined]  # 鸭子类型：summarizer 按契约提供 summarize
                anchors,
                scope=scope,
                project_id=project_id,
                anchor_hash=anchor_hash,
                model=config.llm_default_model,
            )
            if new_summary is not None:
                await repo.upsert(new_summary)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 upsert
                await audit_svc.record(  # type: ignore[attr-defined]  # 鸭子类型：audit 按契约提供 record
                    project_id=project_id,
                    severity_summary="semantic_summary_generated",
                    degraded=True,
                    actor="memory",
                )
                return True
            if dropped:
                await audit_svc.record(  # type: ignore[attr-defined]  # 鸭子类型：audit 按契约提供 record
                    project_id=project_id,
                    severity_summary="semantic_summary_failed",
                    degraded=True,
                    actor="memory",
                    note=f"防幻觉校验丢弃 {dropped} 条",
                )
            return False
    except SemanticSummaryError:
        await _record_failure("后台刷新 LLM 总结失败")
        return False
    except Exception:
        await _record_failure("后台刷新未预期异常")
        return False


async def schedule_summary_background_refresh(
    anchors: list,
    *,
    scope: SummaryScope,
    project_id: uuid.UUID | None,
    anchor_hash: str,
) -> None:
    """fire-and-forget 调度（deps 接线给 PreferenceSource.background_refresh）：
    create_task 后立即返回（注入不等待 LLM，spec §5.4 Q2=B）。"""
    from inkflow.infrastructure.background.tasks import spawn_background_task

    key_suffix = str(project_id) if project_id is not None else "user"
    spawn_background_task(
        run_summary_background_refresh(
            anchors, scope=scope, project_id=project_id, anchor_hash=anchor_hash
        ),
        key=f"summary-refresh-{scope.value}-{key_suffix}",
    )
