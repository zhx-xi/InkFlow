"""F44 访谈式 Planner 服务 - 多轮访谈循环（<=5 问/轮、问题即模板、授权、auto 兜底）.

PlannerService 负责：
- start: 创建 drafting 会话并返回第一轮问题（ROUND1_QUESTIONS / LLM 动态生成）.
- respond: 合并回答 → 授权项记录 → 轮次推进 → 完成时创建 WritingPlan
  （status=ready），并经注入的 outline_service/character_service 直接写
  outline/character 实体（spec 搂2.1 决策论证表）.
- auto: 「全部你决定」直达路径 - declined 会话 + F42 write_auto 委托.

v1.2 #475：装配 llm_client 后升级为真 LLM 动态提问引擎——
- start: LLM 生成第一轮问题（通用必答 + 针对性并存，questions 含 kind），
  缺失必答项服务端补问，LLM 失败降级 ROUND1 确定性常亮.
- respond: 回答合并后调 LLM 提取已确定项（confirmed_items）/冲突（conflicts），
  下轮只问未确定项；必答项齐备且无 pending 冲突 → confirming=true 末尾总体确认，
  confirm=true 完成（不调 LLM）；LLM 失败降级既有 ROUND1→ROUND2 推进.

仅依赖 domain/models 与注入的 repo/可调用对象（鸭子类型），
domain/ 零框架 import 门禁天然满足（ADR-002/015）.

依据: specs/f44-book-orchestrator/spec.md 搂2.2/搂5.1/搂13.5（v1.2）.
"""

from __future__ import annotations

import builtins
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, WritingPlan
from inkflow.domain.services._outline_generator import _extract_json_fragment


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


ROUND1_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "q1",
        "text": "题材：您悬疑为主，还是悬疑+科幻混合？",
        "template": "悬疑为主，但加入 ___ 元素",
        "kind": "general",
    },
    {
        "id": "q2",
        "text": "篇幅：预计多少字？",
        "template": "约 ___ 字",
        "kind": "general",
    },
    {
        "id": "q3",
        "text": "主题：能否一句话描述主题？",
        "template": "主题是 ___",
        "kind": "general",
    },
]
"""第一轮问题（题材/篇幅/主题）：分批节奏 - 大纲/主题必须对话确认."""

ROUND2_QUESTIONS: list[dict[str, str]] = [
    {
        "id": "q4",
        "text": "分卷：需要分几卷？",
        "template": "___ 卷",
        "kind": "general",
    },
    {
        "id": "q5",
        "text": "配角：需要几个主要配角？",
        "template": "___ 个",
        "kind": "general",
    },
]
"""第二轮问题（分卷/配角）：显式授权后细节自定."""

_AUTHORIZE_MARKERS = ("配角自定", "自定")
"""授权触发标记：任一回答包含这些字串即记录授权原文."""

_MUST_ANSWER_KEYS = ("题材", "篇幅", "主题")
"""通用必答项 key（服务端强约束，搂6 R11 ②）：LLM 输出必须覆盖未确认必答项."""

_KEY_NORMALIZE = {
    "genre": "题材",
    "length": "篇幅",
    "theme": "主题",
    "ending": "结局",
    "protagonist_name": "主角",
    "protagonist": "主角",
    "worldview": "世界观",
    "sect": "门派",
    "supporting_character": "配角",
}
"""英文 key → 中文必答项（#517 兜底：LLM 输出自由，合并前收敛；未知英文 key 原样保留）."""

_LLM_TEMPLATE_NAME = "planner_interview"
"""LLM 动态提问模板名（infrastructure/llm/templates/planner_interview.yaml）."""

_LLM_TEMPERATURE = 0.2
"""LLM 动态提问固定低温（结构化输出）."""

_LLM_RETRIES = 1
"""LLM 调用失败/输出不合格重试 1 次（搂7 场景 15 + 搂5.1 服务端强约束）."""


class _PromptMessage(dict):
    """Prompt 消息：dict 视图（测试 .get 断言）+ role/content 属性（真实 LangChain 客户端）."""

    def __init__(self, *, role: str, content: str) -> None:
        super().__init__(role=role, content=content)
        self.role = role
        self.content = content


class PlannerRespondResult(BaseModel):
    """respond 结果：轮次推进或完成返回 WritingPlan."""

    session_id: uuid.UUID
    round: int
    completed: bool
    questions: list[dict] = Field(default_factory=list)
    confirmed_items: list[dict] = Field(default_factory=list)
    """已确定项快照（v1.2 #475：{"key", "value", "source"}）."""
    conflicts: list[dict] = Field(default_factory=list)
    """冲突/回问记录（v1.2 #475：{"round", "question_id", "answer",
    "conflict_with", "resolution"}）."""
    confirming: bool = False
    """末尾总体确认阶段标志（v1.2 #475：必答项齐备后置 True）."""
    writing_plan: WritingPlan | None = None


class PlannerService:
    """访谈式 Planner 服务（v1.2 #475 支持 LLM 动态提问）.

    Args:
        repo: BookRepositoryProtocol（鸭子类型，add/get/update planner_session
            与 writing_plan）.
        write_auto: 可调用 async fn(project_id, one_liner) - F42 委托注入点；
            None = 未装配时 auto 路径报错（防静默降级）.
        outline_service: 鸭子对象（产出整体大纲，返回含 id 的实体）；
            None = 完成路径跳过落库（仅测试隔离用）.
        character_service: 鸭子对象（产出主角 character，返回含 id 的实体）；
            None = 完成路径跳过落库（仅测试隔离用）.
        llm_client: LLMClientProtocol 鸭子对象（async chat → ChatResponse.content
            为结构化 JSON 字符串）；None = 未装配 → 确定性兜底.
        project_context_getter: 可调用 async fn(project_id) -> str（项目设定摘要）；
            None = 空上下文.
        prompt_manager: PromptTemplateProtocol 鸭子对象（load/render）；
            None = 不渲染模板、直接构建最小 prompt.
        outline_repo: 鸭子对象（async get(id) / list(project_id, offset, limit)
            -> (items, total)）；None = 分支起点不可用（#544）.
    """

    def __init__(
        self,
        *,
        repo: object,
        write_auto: Callable[[uuid.UUID, str], Awaitable[object]] | None = None,
        outline_service: object | None = None,
        character_service: object | None = None,
        llm_client: object | None = None,
        project_context_getter: Callable[[uuid.UUID], Awaitable[str]] | None = None,
        prompt_manager: object | None = None,
        outline_repo: object | None = None,
    ) -> None:
        self._repo = repo
        self._write_auto = write_auto
        self._outline_service = outline_service
        self._character_service = character_service
        self._llm_client = llm_client
        self._project_context_getter = project_context_getter
        self._prompt_manager = prompt_manager
        self._outline_repo = outline_repo
        self._last_llm_confirmed_items: list[dict] = []
        """最近一轮 _generate_questions 提取的 confirmed_items（副作用暂存）."""
        self._last_llm_conflicts: list[dict] = []
        """最近一轮 _generate_questions 提取的 conflicts（副作用暂存）."""

    async def start(
        self,
        project_id: uuid.UUID,
        one_liner: str,
        mode: str = "new",
        source_outline_id: uuid.UUID | None = None,
    ) -> PlannerSession:
        """创建 drafting 会话 + 返回第一轮问题（round=1，<=5 问）.

        Args:
            project_id: 所属项目 UUID.
            one_liner: 用户一句话（题材/体裁/篇幅/主题等原始输入）.
            mode: 起点模式（#544）：new / continue / branch.
            source_outline_id: 起点源大纲 id（continue/branch 用；new 为 None）.

        Returns:
            已落库的 PlannerSession（round=1；装配 llm_client 时
            asked_questions=LLM 生成，失败/未装配降级 ROUND1_QUESTIONS）.

        Raises:
            ValueError: mode 非法；branch 缺源大纲；源大纲不存在.
        """
        if mode not in {"new", "continue", "branch"}:
            raise ValueError(f"不支持的起点模式: {mode}")
        copied_outline_id: uuid.UUID | None = None
        if mode == "branch":
            if source_outline_id is None:
                raise ValueError("分支起点需要源大纲")
            copied_outline_id = await self._copy_outline_tree(project_id, source_outline_id)
        if mode == "continue" and source_outline_id is None:
            # 防御：continue 也要求源大纲（契约未显式覆盖，保持宽容不抛——文档注明）
            pass
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
            start_type=mode,
            source_outline_id=source_outline_id,
            copied_outline_id=copied_outline_id,
            writing_plan_id=None,
            created_at=now,
            updated_at=now,
        )
        if self._llm_client is not None:
            questions = await self._generate_questions(session, answers=None)
            if questions is not None:
                session.asked_questions = questions
        await self._repo.add_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 add_planner_session
            session
        )
        return session

    async def _copy_outline_tree(
        self,
        project_id: uuid.UUID,
        source_outline_id: uuid.UUID,
    ) -> uuid.UUID:
        """分支起点：复制源大纲子树（根 + 全部后代，无关大纲不复制），返回新根 id."""
        if self._outline_repo is None:
            raise ValueError("源大纲不存在")
        root: Outline | None = await self._outline_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：构造注入
            source_outline_id
        )
        if root is None:
            raise ValueError("源大纲不存在")
        items, _total = await self._outline_repo.list(  # type: ignore[attr-defined]  # 鸭子类型：构造注入
            project_id, offset=0, limit=50
        )
        ordered: list[Outline] = [root]
        index = 0
        while index < len(ordered):
            parent = ordered[index]
            ordered.extend(o for o in items if o.parent_id == parent.id)
            index += 1
        outline_service = self._outline_service
        if outline_service is None:
            raise ValueError("分支复制未装配大纲服务")
        id_map: dict[uuid.UUID, uuid.UUID] = {}
        for node in ordered:
            name = node.name + "（分支）" if node.parent_id is None else node.name
            created = await outline_service(  # type: ignore[operator]  # 鸭子类型：outline_service 为可调用，产出 outline 实体（含 id）
                project_id,
                name=name,
                description=node.description,
                sort_order=node.sort_order,
                level=node.level,
                parent_id=(id_map[node.parent_id] if node.parent_id is not None else None),
            )
            created_id: uuid.UUID | None = getattr(created, "id", None)
            if created_id is None:
                raise ValueError("分支复制失败：大纲服务未返回 id")
            id_map[node.id] = created_id
        return id_map[root.id]

    async def respond(
        self,
        session_id: uuid.UUID,
        answers: dict[str, str],
        auto: bool = False,
        confirm: bool = False,
    ) -> PlannerRespondResult:
        """处理回答 → 下一轮问 / 完成返回 WritingPlan.

        Args:
            session_id: 会话 UUID.
            answers: 用户回答快照（{"question_id": answer}；
                CLI 单字符串回答用 {"answer": text} 宽容映射到首个未答必答问题）.
            auto: True = 「全部你决定」拒访谈 → 跑 F42 write_auto.
            confirm: True = 末尾总体确认（v1.2 #475：confirming=true 时完成，
                非 confirming 阶段抛 ValueError）.

        Returns:
            PlannerRespondResult（completed=True 时含 WritingPlan）.

        Raises:
            ValueError: 会话不存在；confirm 非确认阶段；auto 路径未装配 write_auto.
        """
        session = await self._repo.get_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_planner_session
            session_id
        )
        if session is None:
            raise ValueError("会话不存在")
        if auto:
            return await self._run_auto(session)
        if confirm:
            if not session.confirming:
                raise ValueError("非确认阶段，请先完成必答项")
            return await self._complete(session)
        self._merge_answers(session, answers)
        session.updated_at = _utcnow()
        if self._llm_client is None:
            return await self._respond_deterministic(session)
        return await self._respond_llm(session, answers)

    async def get(self, session_id: uuid.UUID) -> PlannerSession | None:
        """会话状态快照（asked_questions/answers，问题即模板复用）."""
        return await self._repo.get_planner_session(  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 get_planner_session
            session_id
        )

    async def list(
        self,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[PlannerSession], int]:
        """访谈会话列表（#486 会话页）."""
        return await self._repo.list_planner_sessions(  # type: ignore[no-any-return, attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 list_planner_sessions
            project_id=project_id, status=status, offset=offset, limit=limit
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
            start_type=session.start_type,
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
            start_type=session.start_type,
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
            start_type=session.start_type,
            source_outline_id=session.source_outline_id,
            copied_outline_id=session.copied_outline_id,
            limits={
                "max_chapters": STAGE1_LIMITS.max_chapters,
                "max_agent_calls": STAGE1_LIMITS.max_agent_calls,
            },
            created_at=now,
            updated_at=now,
        )
        if session.start_type == "branch" and session.copied_outline_id is not None:
            plan.root_outline_id = session.copied_outline_id
        elif session.start_type == "continue" and session.source_outline_id is not None:
            plan.root_outline_id = session.source_outline_id
        elif self._outline_service is not None:
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
        """主角名：优先取 confirmed_items 中 key 含「主角」的 value，否则回退 q3 主题回答."""
        for item in session.confirmed_items:
            if "主角" in str(item.get("key", "")):
                value = str(item.get("value", "")).strip()
                if value:
                    return value
        q3 = session.answers.get("q3", "")
        marker = "主角是"
        if marker in q3:
            rest = q3.split(marker, 1)[1].strip()
            if rest:
                return rest
        return "主角"

    async def _respond_llm(
        self,
        session: PlannerSession,
        answers: dict[str, str],
    ) -> PlannerRespondResult:
        """LLM 动态提问引擎：提取确定项/冲突 → 去重过滤 → 必答齐备/轮次推进."""
        llm_result = await self._generate_questions(session, answers)
        if llm_result is None:
            return await self._respond_deterministic(session)

        self._merge_confirmed_items(session, self._last_llm_confirmed_items)
        session.round += 1
        self._apply_conflicts(session, answers, self._last_llm_conflicts)

        confirmed_keys = {str(item.get("key", "")) for item in session.confirmed_items}
        filtered = [
            q for q in llm_result if not any(k in str(q.get("text", "")) for k in confirmed_keys)
        ]

        if self._must_answers_ready(session) and not self._has_pending_conflict(session):
            session.confirming = True
            await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
                session
            )
            return PlannerRespondResult(
                session_id=session.id,
                round=session.round,
                completed=False,
                questions=[],
                confirmed_items=list(session.confirmed_items),
                conflicts=list(session.conflicts),
                confirming=True,
            )

        await self._repo.update_planner_session(  # type: ignore[attr-defined]  # 鸭子类型：repo 按 BookRepositoryProtocol 提供 update_planner_session
            session
        )
        return PlannerRespondResult(
            session_id=session.id,
            round=session.round,
            completed=False,
            questions=filtered,
            confirmed_items=list(session.confirmed_items),
            conflicts=list(session.conflicts),
            confirming=False,
        )

    async def _generate_questions(
        self,
        session: PlannerSession,
        answers: dict[str, str] | None = None,
    ) -> builtins.list[dict] | None:
        """调用 LLM 生成本轮问题（含确定项/冲突提取副作用暂存）.

        重试 1 次（搂7 场景 15）：chat 异常 / 输出不合格 / start 缺失必答项；
        仍失败返回 None 由调用方走确定性兜底；start 仍缺必答项时服务端补问.
        """
        llm_client = self._llm_client
        if llm_client is None:
            return None
        messages = await self._build_prompt_messages(session)
        for attempt in range(_LLM_RETRIES + 1):
            try:
                response: object = await llm_client.chat(  # type: ignore[attr-defined]  # 鸭子类型：llm_client 按 LLMClientProtocol 提供 chat
                    list(messages),
                    temperature=_LLM_TEMPERATURE,
                )
            except Exception:
                if attempt < _LLM_RETRIES:
                    continue
                return None

            content = str(getattr(response, "content", ""))
            parsed = self._parse_llm_payload(content)
            if parsed is None:
                if attempt < _LLM_RETRIES:
                    messages = messages + self._retry_messages(
                        content, "上一版输出无法解析为合法 JSON，请只输出 JSON。"
                    )
                    continue
                return None

            questions, confirmed_items, conflicts = parsed
            if answers is None:
                missing = self._missing_must_answer_keys(session, questions, confirmed_items)
                if missing:
                    if attempt < _LLM_RETRIES:
                        messages = messages + self._retry_messages(
                            content, f"缺失必答项 {', '.join(missing)}，请补充提问。"
                        )
                        continue
                    for key in missing:
                        template_q = next(
                            (q for q in ROUND1_QUESTIONS if key in q.get("text", "")), None
                        )
                        if template_q is not None:
                            questions.append(dict(template_q))
            self._last_llm_confirmed_items = confirmed_items
            self._last_llm_conflicts = conflicts
            return questions
        return None

    async def _build_prompt_messages(self, session: PlannerSession) -> builtins.list[dict]:
        """构建 LLM prompt 消息列表：模板装配优先，未装配手工最小 prompt."""
        ctx = ""
        if self._project_context_getter is not None:
            ctx = await self._project_context_getter(session.project_id)
        hist = self._build_session_history(session)
        if self._prompt_manager is not None:
            template = self._prompt_manager.load(  # type: ignore[attr-defined]  # 鸭子类型：prompt_manager 按 PromptTemplateProtocol 提供 load
                _LLM_TEMPLATE_NAME
            )
            rendered = self._prompt_manager.render(  # type: ignore[attr-defined]  # 鸭子类型：prompt_manager 按 PromptTemplateProtocol 提供 render
                template,
                {
                    "one_liner": session.one_liner,
                    "project_context": ctx,
                    "session_history": hist,
                },
            )
            messages: builtins.list[dict] = [
                _PromptMessage(role=m["role"], content=m["content"]) for m in rendered.messages
            ]
            return messages
        system = (
            "你是小说访谈规划师。根据一句话构思、项目设定摘要与会话历史，"
            "生成下一轮访谈问题（每轮最多 5 问），并提取已确定项、标记冲突。\n"
            f"一句话构思：{session.one_liner}\n"
            f"项目设定摘要：{ctx}\n"
            f"会话历史：{hist}"
        )
        user = (
            '请输出严格 JSON：{"questions": [{"id", "text", "template", "kind"}], '
            '"confirmed_items": [{"key", "value", "source"}], '
            '"conflicts": [{"conflict_with", "resolution"}]}'
        )
        return [
            _PromptMessage(role="system", content=system),
            _PromptMessage(role="user", content=user),
        ]

    @staticmethod
    def _retry_messages(content: str, hint: str) -> builtins.list[dict]:
        """构建重试消息（assistant 原输出 + user 修复提示）."""
        return [
            _PromptMessage(role="assistant", content=content),
            _PromptMessage(role="user", content=hint),
        ]

    @staticmethod
    def _build_session_history(session: PlannerSession) -> str:
        """序列化会话历史（answers/confirmed_items/conflicts）为紧凑文本供 LLM 感知."""
        parts: builtins.list[str] = []
        if session.answers:
            parts.append("已回答：" + "；".join(f"{k}: {v}" for k, v in session.answers.items()))
        if session.confirmed_items:
            parts.append(
                "已确定项："
                + "；".join(
                    f"{item.get('key', '')}={item.get('value', '')}"
                    for item in session.confirmed_items
                )
            )
        if session.conflicts:
            parts.append(
                "冲突记录："
                + "；".join(
                    f"{item.get('conflict_with', '')}[{item.get('resolution', '')}]"
                    for item in session.conflicts
                )
            )
        return "\n".join(parts) if parts else "（无历史）"

    @staticmethod
    def _parse_llm_payload(
        content: str,
    ) -> tuple[builtins.list[dict], builtins.list[dict], builtins.list[dict]] | None:
        """解析 LLM 结构化 JSON 输出（questions/confirmed_items/conflicts），失败返回 None."""
        fragment = _extract_json_fragment(content)
        if fragment is None:
            return None
        try:
            payload: object = json.loads(fragment)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        questions_raw = payload.get("questions")
        confirmed_raw = payload.get("confirmed_items")
        conflicts_raw = payload.get("conflicts")
        if (
            not isinstance(questions_raw, list)
            or not isinstance(confirmed_raw, list)
            or not isinstance(conflicts_raw, list)
        ):
            return None
        questions: builtins.list[dict] = []
        for item in questions_raw:
            if not isinstance(item, dict):
                return None
            if not all(
                isinstance(item.get(key), str) and item.get(key) for key in ("id", "text", "kind")
            ):
                return None
            questions.append(item)
        confirmed_items = [item for item in confirmed_raw if isinstance(item, dict)]
        conflicts = [item for item in conflicts_raw if isinstance(item, dict)]
        return questions, confirmed_items, conflicts

    @staticmethod
    def _missing_must_answer_keys(
        session: PlannerSession,
        questions: builtins.list[dict],
        confirmed_items: builtins.list[dict],
    ) -> builtins.list[str]:
        """计算缺失必答项：未确认且本轮问题文本未覆盖的通用必答项 key."""
        confirmed_keys = {str(item.get("key", "")) for item in confirmed_items}
        confirmed_keys.update(str(item.get("key", "")) for item in session.confirmed_items)
        return [
            key
            for key in _MUST_ANSWER_KEYS
            if key not in confirmed_keys
            and not any(key in str(q.get("text", "")) for q in questions)
        ]

    @staticmethod
    def _merge_confirmed_items(session: PlannerSession, incoming: builtins.list[dict]) -> None:
        """按 key 合并 confirmed_items：新 key 追加、已存在 key 覆盖 value/source."""
        for item in incoming:
            raw_key = item.get("key")
            key = (
                _KEY_NORMALIZE.get(raw_key, raw_key) if isinstance(raw_key, str) else raw_key
            )  # #517 英文→中文兜底
            existing = next(
                (candidate for candidate in session.confirmed_items if candidate.get("key") == key),
                None,
            )
            if existing is None:
                merged = dict(item)
                merged["key"] = key
                session.confirmed_items.append(merged)
            else:
                existing["value"] = item.get("value")
                existing["source"] = item.get("source", existing.get("source"))

    @staticmethod
    def _apply_conflicts(
        session: PlannerSession,
        answers: dict[str, str],
        conflicts: builtins.list[dict],
    ) -> None:
        """LLM 冲突记录补 round/question_id/answer 后追加；resolved 同步标记既有 pending."""
        first_qid = next(iter(answers), "") if answers else ""
        answer_text = answers.get(first_qid, "") if first_qid else ""
        for conflict in conflicts:
            conflict_with = conflict.get("conflict_with")
            resolution = conflict.get("resolution")
            if resolution == "resolved":
                for existing in session.conflicts:
                    if (
                        existing.get("conflict_with") == conflict_with
                        and existing.get("resolution") == "pending"
                    ):
                        existing["resolution"] = "resolved"
            session.conflicts.append(
                {
                    "round": session.round,
                    "question_id": first_qid,
                    "answer": answer_text,
                    "conflict_with": conflict_with,
                    "resolution": resolution,
                }
            )

    @staticmethod
    def _must_answers_ready(session: PlannerSession) -> bool:
        """必答项齐备判定：confirmed_items keys 覆盖 题材/篇幅/主题."""
        keys = {str(item.get("key", "")) for item in session.confirmed_items}
        return all(key in keys for key in _MUST_ANSWER_KEYS)

    @staticmethod
    def _has_pending_conflict(session: PlannerSession) -> bool:
        """是否存在 pending 冲突（存在即必答项未齐备，不得进入末尾总体确认）."""
        return any(c.get("resolution") == "pending" for c in session.conflicts)

    async def _respond_deterministic(self, session: PlannerSession) -> PlannerRespondResult:
        """LLM 失败/未装配的确定性降级路径：复用既有 ROUND1→ROUND2→complete 推进逻辑."""
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


def _first_unanswered(questions: list[dict], answers: dict[str, str]) -> str | None:
    """返回当前轮第一个未答问题 id（宽容映射目标）."""
    for q in questions:
        qid = q.get("id")
        if isinstance(qid, str) and qid not in answers:
            return qid
    return None
