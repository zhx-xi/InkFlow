"""F34 章节审计 confirm 状态机单元测试 — ChapterAuditService.confirm（spec §5.1 ⑨ + §7 E1/E9/E11）.

被测模块: domain/services/chapter_audit_service.py（CREATE；RED 阶段不存在 →
顶部 import 抛 ModuleNotFoundError = 预期收集期失败，pytest 退出码 2）。

覆盖:
- project 不存在 → ProjectNotFoundError（F9 character_errors，404 语义）
- chapter 不存在 → ChapterNotFoundError（F14 extraction_errors，消息含
  「章节不存在」）
- chapter 属于其他项目 → ChapterNotFoundError（消息含「不属于该项目」）
- 无 pending 记录 → NoPendingAuditError（消息「该章无待确认审计」）
- accept: audit_log_repo.confirm 收到 action="accept" + note 透传 +
  confirmed_at（datetime）→ 返回 status="accepted" 的 AuditLog
- reject + note: action="reject" note="人设需再打磨" 透传 → status="rejected"
- 重复 confirm（E9）: 最新记录已非 pending → NoPendingAuditError
- 领域 UUID → int 转换（_to_int_id 模式: uuid.UUID.int）传给 repo

设计假设（GREEN 实现契约，依据 specs/f34-chapter-audit/spec.md §5.1/§3.3）:
1. 模块路径: inkflow.domain.services.chapter_audit_service（CREATE）
2. 构造签名（父侧定死，防并行分歧）: ChapterAuditService(*, project_repo,
   chapter_repo, character_repo, world_repo, audit_service, llm_client,
   audit_log_repo) —— 全部关键字参数
3. confirm 签名: confirm(project_id: uuid.UUID, chapter_id: uuid.UUID, *,
   action: str, note: str = "") -> AuditLog
4. 校验顺序（§5.1 ⑨ + §3.3 异常映射）: ① 项目存在（project_repo.get → None
   → ProjectNotFoundError）→ ② 章节存在且属于该项目（chapter_repo
   .get_chapter → None → ChapterNotFoundError；project_id 不匹配 →
   ChapterNotFoundError 消息含「不属于该项目」）→ ③ 该章最新记录为 pending
   （audit_log_repo.latest_pending → None → NoPendingAuditError）→
   ④ audit_log_repo.confirm 更新并返回
5. 错误类归属: ProjectNotFoundError 复用 F9 character_errors（非 F15
   audit_errors 同名类——若实现误用 F15 类，pytest.raises 将不捕获而 FAIL）；
   ChapterNotFoundError 复用 F14 extraction_errors；NoPendingAuditError 为
   F34 自有（inkflow.domain.ports.chapter_audit_errors，消息「该章无待确认
   审计」，E12 文案）——陷阱 16: 错误类不导出到 ports/__init__.py，本文件
   守护断言 not hasattr(inkflow.domain.ports, "NoPendingAuditError")
   （RED 阶段即 PASS）
6. repo 调用 id 一律 int（uuid.UUID.int）: latest_pending(chapter_id.int)、
   confirm(log_id.int, action=..., note=..., confirmed_at=datetime.now(UTC))
   ——confirm 的 log_id 取 latest_pending 返回记录的 id
7. 本文件 mock repos + mock audit_log_repo（AsyncMock），不触碰真实 DB
8. RED 预期: 收集期 1 error（ModuleNotFoundError: No module named
   'inkflow.domain.models.chapter_audit'——import 字母序使其先于
   chapter_audit_service / chapter_audit_errors 失败；GREEN 后模块落地
   即自动收集），无其他失败
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import inkflow.domain.ports as ports_module
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.chapter_audit import AuditLog
from inkflow.domain.models.project import Project
from inkflow.domain.ports.chapter_audit_errors import NoPendingAuditError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.services.chapter_audit_service import ChapterAuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
OTHER_PID = uuid.UUID("4f4f4f4f-4f4f-4f4f-8f4f-4f4f4f4f4f4f")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _project() -> Project:
    """构造测试项目（属于 PID）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _chapter(*, project_id: uuid.UUID = PID) -> Chapter:
    """构造测试章节实体（默认属于 PID）。"""
    return Chapter(id=CID, project_id=project_id, title="第 3 章 龙的苏醒")


def make_log(**overrides: Any) -> AuditLog:
    """构造最小合法审计记录（镜像 test_chapter_audit_models.py make_log 工厂）。"""
    base = {
        "id": uuid.UUID(int=1),
        "project_id": PID,
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 2 warnings, 0 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
    }
    base.update(overrides)
    return AuditLog(**base)


@pytest.fixture
def svc():
    """构造被测服务（全部依赖 AsyncMock；裸 AsyncMock 任意属性可配置）。

    svc.service 为被测实例；svc.<依赖名> 为对应 mock。
    """
    mocks = {
        "project_repo": AsyncMock(),
        "chapter_repo": AsyncMock(),
        "character_repo": AsyncMock(),
        "world_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "llm_client": AsyncMock(),
        "audit_log_repo": AsyncMock(),
    }
    service = ChapterAuditService(**mocks)
    return SimpleNamespace(service=service, **mocks)


class TestConfirmValidation:
    """confirm 前置校验（§3.3 异常映射: 404 语义）。"""

    async def test_project_not_found_raises(self, svc):
        svc.project_repo.get.return_value = None
        with pytest.raises(ProjectNotFoundError) as exc_info:
            await svc.service.confirm(PID, CID, action="accept")
        assert "项目不存在" in str(exc_info.value)
        svc.chapter_repo.get_chapter.assert_not_awaited()
        svc.audit_log_repo.latest_pending.assert_not_awaited()

    async def test_chapter_not_found_raises(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = None
        with pytest.raises(ChapterNotFoundError) as exc_info:
            await svc.service.confirm(PID, CID, action="accept")
        assert "章节不存在" in str(exc_info.value)
        svc.audit_log_repo.latest_pending.assert_not_awaited()

    async def test_chapter_of_other_project_raises(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter(project_id=OTHER_PID)
        with pytest.raises(ChapterNotFoundError) as exc_info:
            await svc.service.confirm(PID, CID, action="accept")
        assert "不属于该项目" in str(exc_info.value)
        svc.audit_log_repo.latest_pending.assert_not_awaited()

    async def test_no_pending_log_raises(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter()
        svc.audit_log_repo.latest_pending.return_value = None
        with pytest.raises(NoPendingAuditError) as exc_info:
            await svc.service.confirm(PID, CID, action="accept")
        assert "该章无待确认审计" in str(exc_info.value)
        svc.audit_log_repo.confirm.assert_not_awaited()


class TestConfirmAccept:
    """accept 路径（§5.1 ⑨: status=accepted + confirmed_at + note）。"""

    async def test_accept_updates_and_returns_accepted_log(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter()
        pending = make_log()
        svc.audit_log_repo.latest_pending.return_value = pending
        confirmed = make_log(
            status="accepted", confirmed_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC)
        )
        svc.audit_log_repo.confirm.return_value = confirmed

        result = await svc.service.confirm(PID, CID, action="accept")

        assert isinstance(result, AuditLog)
        assert result.status == "accepted"
        assert result.confirmed_at is not None

    async def test_accept_passes_int_ids_and_params_to_repo(self, svc):
        """领域 UUID → int 转换（_to_int_id 模式）: repo 收到 int id。"""
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter()
        pending = make_log()
        svc.audit_log_repo.latest_pending.return_value = pending
        svc.audit_log_repo.confirm.return_value = make_log(
            status="accepted", confirmed_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC)
        )

        await svc.service.confirm(PID, CID, action="accept")

        svc.project_repo.get.assert_awaited_once_with(PID.int)
        svc.chapter_repo.get_chapter.assert_awaited_once_with(CID.int)
        svc.audit_log_repo.latest_pending.assert_awaited_once_with(CID.int)
        args, kwargs = svc.audit_log_repo.confirm.await_args
        assert args[0] == pending.id.int
        assert kwargs["action"] == "accept"
        assert kwargs["note"] == ""
        assert isinstance(kwargs["confirmed_at"], datetime)


class TestConfirmReject:
    """reject 路径（§5.1 ⑨: status=rejected + note 落库透传）。"""

    async def test_reject_with_note_passthrough(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter()
        svc.audit_log_repo.latest_pending.return_value = make_log()
        svc.audit_log_repo.confirm.return_value = make_log(
            status="rejected",
            note="人设需再打磨",
            confirmed_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC),
        )

        result = await svc.service.confirm(PID, CID, action="reject", note="人设需再打磨")

        assert result.status == "rejected"
        assert result.note == "人设需再打磨"
        _, kwargs = svc.audit_log_repo.confirm.await_args
        assert kwargs["action"] == "reject"
        assert kwargs["note"] == "人设需再打磨"


class TestConfirmRepeat:
    """重复 confirm（§7 E9: 已确认过 → 无 pending → 422 语义）。"""

    async def test_second_confirm_after_accepted_raises(self, svc):
        svc.project_repo.get.return_value = _project()
        svc.chapter_repo.get_chapter.return_value = _chapter()
        svc.audit_log_repo.latest_pending.return_value = make_log()
        svc.audit_log_repo.confirm.return_value = make_log(
            status="accepted", confirmed_at=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC)
        )

        first = await svc.service.confirm(PID, CID, action="accept")
        assert first.status == "accepted"

        # 最新记录已非 pending → 第二次 confirm 拒绝
        svc.audit_log_repo.latest_pending.return_value = None
        with pytest.raises(NoPendingAuditError):
            await svc.service.confirm(PID, CID, action="accept")


class TestErrorClassExport:
    """错误类归属与导出（陷阱 16: 不导出到 ports/__init__.py）。"""

    def test_no_pending_error_not_exported_from_ports_init(self):
        """守护断言（RED 阶段即 PASS）: 错误类由模块自身导出，不 export 到 __init__。"""
        assert not hasattr(ports_module, "NoPendingAuditError")
