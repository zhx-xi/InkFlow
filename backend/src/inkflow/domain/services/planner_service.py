"""F44 访谈式 Planner 服务 - 多轮访谈循环（<=5 问/轮、问题即模板、授权、auto 兜底）.

PlannerService 负责：
- start: 创建 drafting 会话并返回第一轮问题（ROUND1_QUESTIONS）.
- respond: 合并回答 → 授权项记录 → 轮次推进 → 完成时创建 WritingPlan
  （status=ready），并经注入的 outline_service/character_service 直接写
  outline/character 实体（spec 搂2.1 决策论证表）.
- auto: 「全部你决定」直达路径 - declined 会话 + F42 write_auto 委托.

仅依赖 domain/models 与注入的 repo/可调用对象（鸭子类型），
domain/ 零框架 import 门禁天然满足（ADR-002/015）.

依据: specs/f44-long-task-orchestrator/spec.md 搂2.2/搂5.1/搂13.1（v1.1）.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, WritingPlan


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


ROUND1_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "q1",
        "text": "题材：您悬疑为主，还是悬疑+科幻混合？",
        "template": "悬疑为主，但加入 ___ 元素",
    },
    {
        "id": "q2",
        "text": "篇幅：预计多少字？",
        "template": "约 ___ 字",
    },
    {
        "id": "q3",
        "text": "主题：能否一句话描述主题？",
        "template": "主题是 ___",
    },
]
"""第一轮问题（题材/篇幅/主题）：分批节奏 - 大纲/主题必须对话确认."""

ROUND2_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "q4",
        "text": "分卷：需要分几卷？",
        "template": "___ 卷",
    },
    {
        "id": "q5",
        "text": "配角：需要几个主要配角？",
        "template": "___ 个",
    },
]
"""第二轮问题（分卷/配角）：显式授权后细节自定."""

_AUTHORIZE_MARKERS = ("配角自定", "自定")
"""授权触发标记：任一回答包含这些字串即记录授权原文."""


class PlannerRespondResult(BaseModel):
    """respond 结果：轮次推进或完成返回 WritingPlan."""

    session_id: uuid.UUID
    round: int
    completed: bool
    questions: list[dict] = Field(default_factory=list)
    writing_plan: WritingPlan | None = None


class PlannerService:
    """访谈式 Planner 服务.

    Args:
        repo: BookRepositoryProtocol（鸭子类型，add/get/update planner_session
            与 writing_plan）.
        write_auto: 可调用 async fn(project_id, one_liner) - F42 委托注入点；
            None = 未装配时 auto 路径报错（防静默降级）.
        outline_service: 鸭子对象（产出整体大纲，返回含 id 的实体）；
            None = 完成路径跳过落库（仅测试隔离用）.
        character_service: 鸭子对象（产出主角 character，返回含 id 的实体）；
            None = 完成路径跳过落库（仅测试隔离用）.
    """

    def __init__(
        self,
        *,
        repo: object,
        write_auto: Callable[[uuid.UUID, str], Awaitable[object]] | None = None,
        outline_service: object | None = None,
        character_service: object | None = None,
    ) -> None:
        self._repo = repo
        self._write_auto = write_auto
        self._outline_service = outline_service
        self._character_service = character_service

    async def start(self, project_id: uuid.UUID, one_liner: str) -> PlannerSession:
        """创建 drafting 会话 + 返回第一轮问题（round=1，<=5 问）.

        Args:
            project_id: 所属项目 UUID.
            one_liner: 用户一句话（题材/体裁/篇幅/主题等原始输入）.

        Returns:
            已落库的 PlannerSession（round=1，asked_questions=ROUND1_QUESTIONS）.
        """
        now = _utcnow()
        session = PlannerSession(
            id=uuid.uuid4(),
            project_id=project_id,
            status="drafting",
            one_liner=one_liner,
            round=1,
            asked_questions=list(ROUND1_QUESTIONS),
            answers={},
            authorized=[],
            writing_plan_id=None,
            created_at=now,
            updated_at=now,
        )
        await self._repo.add_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_planner_session
            session
        )
        return session

    async def respond(
        self,
        session_id: uuid.UUID,
        answers: dict[str, str],
        auto: bool = False,
    ) -> PlannerRespondResult:
        """处理回答 → 下一轮问 / 完成返回 WritingPlan.

        Args:
            session_id: 会话 UUID.
            answers: 用户回答快照（{"question_id": answer}；
                CLI 单字符串回答用 {"answer": text} 宽容映射到首个未答必答问题）.
            auto: True = 「全部你决定」拒访谈 → 跑 F42 write_auto.

        Returns:
            PlannerRespondResult（completed=True 时含 WritingPlan）.

        Raises:
            ValueError: 会话不存在；或 auto 路径未装配 write_auto.
        """
        session = await self._repo.get_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_planner_session
            session_id
        )
        if session is None:
            raise ValueError("会话不存在")
        if auto:
            return await self._run_auto(session)
        self._merge_answers(session, answers)
        session.updated_at = _utcnow()
        if session.round == 1 and self._round1_complete(session):
            session.round = 2
            session.asked_questions = list(ROUND2_QUESTIONS)
            await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
                session
            )
            return PlannerRespondResult(
                session_id=session.id,
                round=session.round,
                completed=False,
                questions=list(session.asked_questions),
            )
        if session.round >= 5 or self._round2_complete(session):
            return await self._complete(session)
        await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
            session
        )
        return PlannerRespondResult(
            session_id=session.id,
            round=session.round,
            completed=False,
            questions=list(session.asked_questions),
        )

    async def get(self, session_id: uuid.UUID) -> PlannerSession | None:
        """会话状态快照（asked_questions/answers，问题即模板复用）."""
        return await self._repo.get_planner_session(  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_planner_session
            session_id
        )

    async def auto(self, project_id: uuid.UUID, one_liner: str) -> WritingPlan:
        """「全部你决定」直达路径：declined 会话 + write_auto 委托.

        Args:
            project_id: 所属项目 UUID.
            one_liner: 用户一句话.

        Returns:
            WritingPlan（status=auto）.

        Raises:
            ValueError: 未装配 write_auto.
        """
        if self._write_auto is None:
            raise ValueError("write_auto 未装配")
        now = _utcnow()
        session = PlannerSession(
            id=uuid.uuid4(),
            project_id=project_id,
            status="declined",
            one_liner=one_liner,
            round=1,
            asked_questions=[],
            answers={},
            authorized=[],
            writing_plan_id=None,
            created_at=now,
            updated_at=now,
        )
        await self._repo.add_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_planner_session
            session
        )
        await self._write_auto(project_id, one_liner)
        plan = WritingPlan(
            id=uuid.uuid4(),
            project_id=project_id,
            title=one_liner,
            status="auto",
            limits={
                "max_chapters": STAGE1_LIMITS.max_chapters,
                "max_agent_calls": STAGE1_LIMITS.max_agent_calls,
            },
            created_at=now,
            updated_at=now,
        )
        await self._repo.add_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_writing_plan
            plan
        )
        session.writing_plan_id = plan.id
        await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
            session
        )
        return plan

    async def _run_auto(self, session: PlannerSession) -> PlannerRespondResult:
        """respond(auto=True)：拒访谈（declined）→ write_auto → WritingPlan(status=auto)."""
        if self._write_auto is None:
            raise ValueError("write_auto 未装配")
        session.status = "declined"
        session.updated_at = _utcnow()
        await self._write_auto(session.project_id, session.one_liner)
        plan = WritingPlan(
            id=uuid.uuid4(),
            project_id=session.project_id,
            title=session.one_liner,
            status="auto",
            limits={
                "max_chapters": STAGE1_LIMITS.max_chapters,
                "max_agent_calls": STAGE1_LIMITS.max_agent_calls,
            },
            created_at=session.updated_at,
            updated_at=session.updated_at,
        )
        await self._repo.add_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_writing_plan
            plan
        )
        session.writing_plan_id = plan.id
        await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
            session
        )
        return PlannerRespondResult(
            session_id=session.id,
            round=session.round,
            completed=True,
            writing_plan=plan,
        )

    async def _complete(self, session: PlannerSession) -> PlannerRespondResult:
        """完成路径：创建 WritingPlan(status=ready) + planner 产出落库 + 会话关联."""
        now = _utcnow()
        plan = WritingPlan(
            id=uuid.uuid4(),
            project_id=session.project_id,
            title=session.one_liner,
            status="ready",
            limits={
                "max_chapters": STAGE1_LIMITS.max_chapters,
                "max_agent_calls": STAGE1_LIMITS.max_agent_calls,
            },
            created_at=now,
            updated_at=now,
        )
        if self._outline_service is not None:
            outline = await self._outline_service(  # type: ignore[operator]  # 鸭子类型：outline_service 为可调用，产出 outline 实体（含 id）
                project_id=session.project_id,
                name=self._outline_name(session),
                description=session.one_liner,
                level="overall",
            )
            plan.root_outline_id = getattr(outline, "id", None)
        if self._character_service is not None:
            character = await self._character_service(  # type: ignore[operator]  # 鸭子类型：character_service 为可调用，产出 character 实体（含 id）
                project_id=session.project_id,
                name=self._protagonist_name(session),
            )
            char_id = getattr(character, "id", None)
            if char_id is not None:
                plan.character_ids.append(char_id)
        await self._repo.add_writing_plan(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_writing_plan
            plan
        )
        session.status = "completed"
        session.writing_plan_id = plan.id
        session.updated_at = now
        await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
            session
        )
        return PlannerRespondResult(
            session_id=session.id,
            round=session.round,
            completed=True,
            writing_plan=plan,
        )

    @staticmethod
    def _merge_answers(session: PlannerSession, answers: dict[str, str]) -> None:
        """合并回答：宽容映射 + 授权项记录（去重）."""
        if "answer" in answers:
            target = _first_unanswered(session.asked_questions, session.answers)
            if target is not None:
                session.answers[target] = answers["answer"]
            return
        for qid, text in answers.items():
            if not text.strip():
                continue
            session.answers[qid] = text
            if (
                any(marker in text for marker in _AUTHORIZE_MARKERS)
                and text not in session.authorized
            ):
                session.authorized.append(text)

    @staticmethod
    def _round1_complete(session: PlannerSession) -> bool:
        """轮 1 完成条件：q1-q3 全部已回答（大纲/主题必须对话确认）."""
        return all(q["id"] in session.answers for q in ROUND1_QUESTIONS)

    @staticmethod
    def _round2_complete(session: PlannerSession) -> bool:
        """轮 2 完成条件：q4/q5 已回答或已授权（配角/细节显式授权后自定）."""
        return all(q["id"] in session.answers for q in ROUND2_QUESTIONS) or bool(session.authorized)

    @staticmethod
    def _outline_name(session: PlannerSession) -> str:
        """整体大纲名称：含书名（一句话标题）与题材标记."""
        title = session.one_liner.strip() or "未命名书"
        return f"{title}（书级大纲）"

    @staticmethod
    def _protagonist_name(session: PlannerSession) -> str:
        """主角名：优先取 q3 主题回答中的「主角是 X」片段，否则用默认占位."""
        q3 = session.answers.get("q3", "")
        marker = "主角是"
        if marker in q3:
            rest = q3.split(marker, 1)[1].strip()
            if rest:
                return rest
        return "主角"


def _first_unanswered(questions: list[dict], answers: dict[str, str]) -> str | None:
    """返回当前轮第一个未答问题 id（宽容映射目标）."""
    for q in questions:
        qid = q.get("id")
        if isinstance(qid, str) and qid not in answers:
            return qid
    return None
