"""ChapterAuditService 异步语义混入（#1425）—— 受理 / 后台执行 / 轮询读口.

拆文件动机：`chapter_audit_service.py` 触 monster file ban（>900 行，
`ci_cd/check_file_length.py` 门禁）——#1425 新增的 HTTP 异步面（submit /
run_audit_job / get_status）与「HTTP 触发路径」自洽，可独立成 mixin，与
`BookRunMixin`（#456）同款：**不改类契约**（`ChapterAuditService` 混入后这些
仍是实例方法，既有调用点/测试零改动）；被混入的属性/方法由主类提供，故以
`type: ignore[attr-defined]`（每处带中文理由）抑制 mypy 的 attr-defined 误报。

依据: specs/f34-chapter-audit/spec.md §5.1（v1.5）/§7 E8/E19-E22 · issue #1425.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from inkflow.domain.models.chapter_audit import AuditLog, AuditRunStatus
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError

REUSE_STALE_SECONDS = 900
"""运行中记录的复用窗口秒数（#1425 幂等重跑，spec §7 E8/E21）。

单章审计实测 65~305s（#1420）→ 900s 留足余量。窗口外的 `running` 视为内核崩溃
遗留：**不复用**（不阻塞重审），但也不改写（#1317「不误伤别实例」纪律）。
"""


def to_uuid(value: int | uuid.UUID) -> uuid.UUID:
    """将 int 或 UUID 统一转为 uuid.UUID（#1291：仅兼容外部 int 入参，非仓库层中转）."""
    if isinstance(value, int):
        return uuid.UUID(int=value)
    return value


def content_hash(content: str) -> str:
    """章节正文内容指纹（sha256 hex，幂等去重键；#1425）.

    Args:
        content: 章节正文（空串亦可——空章节仍有稳定指纹）.

    Returns:
        64 位十六进制 sha256 摘要.
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


class ChapterAuditAsyncMixin:
    """审计异步语义（#1425）——供 `ChapterAuditService` 混入.

    ⚠️ 本混入假定主类提供 `_project_repo` / `_chapter_repo` / `_audit_log_repo`
    三个仓储与 `_run_checks` / `_severity_summary` 两个方法（见主类 `__init__`）。
    """

    async def submit(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID,
        *,
        include_static: bool = True,
        now: datetime | None = None,
    ) -> tuple[AuditLog, bool]:
        """受理审计请求（#1425 异步语义，spec §5.1 v1.5 ①-④）——**不执行检查**.

        HTTP 触发路径的入口：校验项目/章节（404 语义，受理前）→ 以
        `(chapter_id, sha256(正文))` 查幂等复用（spec §7 E8）→ 命中则复用既有记录
        （**不新增**，`created=False`）；未命中则落一条 `run_status='running'` 记录
        （`status='pending'`、`severity_summary=''`、`findings=[]`）→ `created=True`。
        调用方据 `created` 决定是否派发后台任务（`run_audit_job`）。

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 待审计章节 UUID.
            include_static: 是否包含 F15 静态一致性委托（透传给后台任务）.
            now: 受理时间（测试注入；缺省 UTC now）.

        Returns:
            (审计记录, 是否新建)——新建为 True（须派发后台任务），复用为 False.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
            ChapterNotFoundError: 章节不存在或属于其他项目（404 语义）.
        """
        project = await self._project_repo.get(  # type: ignore[attr-defined]  # 混入类：属性由 ChapterAuditService 提供
            project_id
        )
        if project is None:
            raise ProjectNotFoundError()
        cid = to_uuid(chapter_id)
        chapter = await self._chapter_repo.get_chapter(cid)  # type: ignore[attr-defined]  # 混入类：属性由主类提供
        if chapter is None:
            raise ChapterNotFoundError()
        if chapter.project_id != project_id:
            raise ChapterNotFoundError("章节不属于该项目")

        current = now or datetime.now(UTC)
        fingerprint = content_hash(chapter.content)
        existing = await self._audit_log_repo.find_reusable(  # type: ignore[attr-defined]  # 混入类：属性由主类提供
            cid,
            fingerprint,
            stale_before=current - timedelta(seconds=REUSE_STALE_SECONDS),
        )
        if existing is not None:
            return existing, False

        created: AuditLog = await self._audit_log_repo.add(  # type: ignore[attr-defined]  # 混入类：属性由主类提供
            AuditLog(
                id=uuid.uuid4(),
                project_id=project_id,
                chapter_id=cid,
                chapter_title=chapter.title,
                status="pending",
                run_status=AuditRunStatus.RUNNING,
                severity_summary="",
                summary="",
                degraded=False,
                note="",
                created_at=current,
                confirmed_at=None,
                error="",
            ),
            findings=[],
            content_hash=fingerprint,
        )
        return created, True

    async def run_audit_job(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID,
        log_id: uuid.UUID,
        *,
        include_static: bool = True,
    ) -> None:
        """后台执行体（#1425，fire-and-forget）——成功 `complete()` / 异常 `fail()`.

        **绝不抛出**：后台任务无 HTTP 请求上下文承载异常，失败必须落
        `audit_logs.run_status='failed'` + `error`（spec §7 E19），供客户端轮询收口。
        「LLM 失败降级不阻塞」（§5.3）语义不变：异步下体现为
        `run_status='completed'` + `degraded=true`。

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 待审计章节 UUID.
            log_id: 受理时落库的审计记录 ID（submit 已建 running 记录）.
            include_static: 是否包含 F15 静态一致性委托.
        """
        try:
            report, _chapter = await self._run_checks(  # type: ignore[attr-defined]  # 混入类：方法由主类提供
                project_id, chapter_id, include_static=include_static
            )
        except Exception as exc:
            logger.warning(
                "章节审计后台任务失败（log_id={}）: {}: {}", log_id, type(exc).__name__, exc
            )
            with contextlib.suppress(Exception):
                await self._audit_log_repo.fail(  # type: ignore[attr-defined]  # 混入类：属性由主类提供
                    to_uuid(log_id), error=f"审计任务失败: {exc}"
                )
            return
        severity_summary: str = self._severity_summary(report.findings)  # type: ignore[attr-defined]  # 混入类：方法由主类提供
        await self._audit_log_repo.complete(  # type: ignore[attr-defined]  # 混入类：属性由主类提供
            to_uuid(log_id),
            findings=report.findings,
            severity_summary=severity_summary,
            summary=report.summary,
            degraded=report.degraded,
        )

    async def get_status(self, log_id: uuid.UUID) -> AuditLog:
        """按审计记录 ID 取轻量状态（#1425 轮询读口，spec §3.1）.

        Args:
            log_id: 审计记录 UUID.

        Returns:
            轻量 AuditLog（含 run_status/error；不含 findings 解析）.

        Raises:
            AuditLogNotFoundError: 记录不存在（404 语义）.
        """
        log: Any = await self._audit_log_repo.get_status(  # type: ignore[attr-defined]  # 混入类：属性由主类提供
            to_uuid(log_id)
        )
        if log is None:
            raise AuditLogNotFoundError()
        return log  # type: ignore[no-any-return]  # 仓储返回 AuditLog（结构契约）
