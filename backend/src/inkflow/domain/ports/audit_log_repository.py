"""审计日志仓储端口 — F34 章节审计轻量记录持久化契约.

AuditLogRepositoryProtocol 定义 audit_logs 轻量记录（Q1=C）的 CRUD 契约：
add 插入一条审计记录并返回含 ORM 主键背书的领域实体；latest_pending 取该章
最新 pending 记录（确认状态机前置校验）；confirm 落库确认动作/备注/时间；
list 按项目分页查询（可追溯入口）。基础设施层
（SQLiteAuditLogRepository，infrastructure/database/repositories/
audit_log_repo.py）结构化实现此 Protocol。

依据: specs/f34-chapter-audit/spec.md §8.1/§8.2。
"""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from inkflow.domain.models.chapter_audit import AuditLog, AuditLogDetail, ChapterAuditFinding


class AuditLogRepositoryProtocol(Protocol):
    """审计日志仓储端口（spec §8.1，F15 audit_repo 先例）.

    所有 id 参数/返回均为 int 主键或 uuid.UUID(int=...) 背书形式，
    领域 UUID ↔ ORM int 转换在仓储实现层完成。
    """

    async def add(
        self,
        log: AuditLog,
        *,
        findings: Sequence[ChapterAuditFinding] | None = None,
        content_hash: str = "",
    ) -> AuditLog:
        """插入一条审计记录（含 findings 快照 + 内容指纹），返回含 ORM 主键背书的 AuditLog.

        Args:
            log: 领域审计记录（id 由仓储按 ORM 自增主键生成）.
            findings: 审计发现快照（#1420）；None/空 → 落空列表.
            content_hash: 章节正文 sha256 指纹（#1425 幂等去重键）；缺省空串（永不命中）.

        Returns:
            已落库的 AuditLog（id = uuid.UUID(int=orm_id)）.
        """
        ...

    async def find_reusable(
        self,
        chapter_id: uuid.UUID,
        content_hash: str,
        *,
        stale_before: datetime,
    ) -> AuditLog | None:
        """查找可复用的既有审计记录（#1425 幂等重跑，spec §7 E8）.

        复用谓词（同章 + 同 `content_hash`，取 created_at 最新一条）：
        ① `run_status='running'` 且 `created_at >= stale_before`（窗口内并发去重），或
        ② `run_status='completed'` 且 `status='pending'` 且 `degraded=False`（已审待确认）。

        窗口外 running（疑似内核崩溃遗留）不复用——不阻塞重审（E21）。

        Args:
            chapter_id: 章节主键（领域 UUID，见 #1291）.
            content_hash: 章节正文 sha256 指纹；空串 → 永不命中.
            stale_before: running 记录的有效下界（更早视为遗留）.

        Returns:
            可复用的 AuditLog（复用面只读确认态字段）；无 → None.
        """
        ...

    async def complete(
        self,
        log_id: uuid.UUID,
        *,
        findings: Sequence[ChapterAuditFinding],
        severity_summary: str,
        summary: str,
        degraded: bool,
    ) -> AuditLog | None:
        """标记审计任务完成（#1425）：落 findings 快照 + 摘要，`run_status='completed'`.

        Args:
            log_id: 审计记录主键（领域 UUID）.
            findings: 审计发现快照（与报告同源）.
            severity_summary: 严重级别摘要（计数落库）.
            summary: LLM 一句话总结（可空）.
            degraded: LLM 降级标记.

        Returns:
            更新后的 AuditLog；log_id 不存在 → None.
        """
        ...

    async def fail(self, log_id: uuid.UUID, *, error: str) -> AuditLog | None:
        """标记审计任务失败（#1425）：`run_status='failed'` + `error` 落库.

        Args:
            log_id: 审计记录主键（领域 UUID）.
            error: 失败原因（人类可读，供客户端轮询/`--wait` 展示）.

        Returns:
            更新后的 AuditLog；log_id 不存在 → None.
        """
        ...

    async def get_status(self, log_id: uuid.UUID) -> AuditLog | None:
        """按 ID 取轻量记录（#1425 轮询读口）——不含 findings 解析.

        Args:
            log_id: 审计记录主键（领域 UUID）.

        Returns:
            轻量 AuditLog（含 run_status/error）；不存在 → None.
        """
        ...

    async def get(self, log_id: uuid.UUID) -> AuditLogDetail | None:
        """按审计记录 ID 取回明细（#1420 读口）.

        Args:
            log_id: 审计记录主键（领域 UUID，见 #1291）.

        Returns:
            含 findings 快照的 AuditLogDetail；log_id 不存在 → None.
        """
        ...

    async def latest_pending(self, chapter_id: uuid.UUID) -> AuditLog | None:
        """返回该章最新 pending 审计记录（created_at desc 取最新）.

        Args:
            chapter_id: 章节主键（领域 UUID，见 #1291）.

        Returns:
            最新 pending 记录；该章无 pending（已全部确认/从未审计）→ None.
        """
        ...

    async def confirm(
        self, log_id: uuid.UUID, *, action: str, note: str, confirmed_at: datetime
    ) -> AuditLog | None:
        """确认审计记录（action 映射为 status + note + confirmed_at 落库）.

        Args:
            log_id: 审计记录主键（领域 UUID，见 #1291）.
            action: 确认动作（accept→accepted / reject→rejected）.
            note: 确认备注（拒绝原因等）.
            confirmed_at: 确认时间（UTC）.

        Returns:
            更新后的 AuditLog；log_id 不存在 → None.
        """
        ...

    async def list(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> tuple[builtins.list[AuditLog], int]:
        """按项目分页查询审计记录（created_at desc 最新在前）.

        Args:
            project_id: 项目主键（领域 UUID，见 #1291）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 20）.

        Returns:
            (页内 AuditLog 列表, 该项目审计记录总数).
        """
        ...
