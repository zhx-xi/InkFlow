"""F27 审计日志服务——F34 audit_logs 薄封装（拍板 A）.

F34 无 audit_log_service 封装（只有 repo），F27 自建薄封装：
动作语义用 severity_summary 承载（"draft_saved"/"draft_confirmed"/"draft_rejected" 等），
不扩表结构（spec §5.5）；actor 拼入 summary 前缀（AuditLog 无 actor 字段）。

record 内捕获一切异常并返回 None——审计是旁路，记录失败不影响主流程。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from inkflow.domain.models.chapter_audit import AuditLog
from inkflow.domain.ports.audit_log_repository import AuditLogRepositoryProtocol


class AuditLogService:
    """审计日志服务——包装 SQLiteAuditLogRepository（F34 表，severity_summary 承载动作语义）.

    Args:
        repo: SQLiteAuditLogRepository（鸭子类型，结构实现 AuditLogRepositoryProtocol）.
    """

    def __init__(self, repo: AuditLogRepositoryProtocol) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        chapter_title: str = "",
        status: Literal["pending", "accepted", "rejected"] = "pending",
        severity_summary: str = "",
        summary: str = "",
        degraded: bool = False,
        note: str = "",
        actor: str = "",
    ) -> AuditLog | None:
        """写一条审计日志（actor 拼入 summary 前缀；异常静默返回 None 不影响主流程）.

        Args:
            project_id: 所属项目 UUID（真实体系，int 背书；.int 转换在 F34 repo.add 内完成）.
            chapter_id: 所属章节 UUID（可空——save_draft 未绑定章节时审计可空）.
            chapter_title: 章节标题快照（默认空）.
            status: 确认状态（默认 pending）.
            severity_summary: 动作语义摘要（如 "draft_saved"）.
            summary: 一句总结（actor 非空时前缀 `[actor] `）.
            degraded: LLM 降级标记（默认 False）.
            note: 备注（默认空）.
            actor: 动作主体（如 "agent:writer"）.

        Returns:
            已落库的 AuditLog（id = uuid.UUID(int=orm_id)）；记录失败 → None（不抛出）.
        """
        if actor:
            summary = f"[{actor}] {summary}"
        log = AuditLog(
            id=uuid.uuid4(),  # 占位：repo 以 ORM 自增主键背书
            project_id=project_id,
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            status=status,
            severity_summary=severity_summary,
            summary=summary,
            degraded=degraded,
            note=note,
            created_at=datetime.now(UTC),
            confirmed_at=None,
        )
        try:
            return await self._repo.add(log)
        except Exception:
            return None
