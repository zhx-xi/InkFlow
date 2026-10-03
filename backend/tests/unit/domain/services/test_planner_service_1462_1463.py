"""#1462 + #1463 planner 同族双修契约测试（TDD RED 阶段）。

权威来源：issue #1462 / #1463 的「现象 + 根因（file:line）+ 修复方向」。

════════════════════════════════════════════════════════════════════
缺陷 A（#1462）：项目级模型永不生效
  根因链：
    planner_service._generate_questions
      → self._project_repo.get(session.project_id.int)   # 传裸 int
      → SQLiteProjectRepository.get → require_uuid_pk(裸 int) → TypeError
        （ADR-060 D9 / #1291：调用方不应自行 .int）
      → except Exception: project_model = None            # 静默吞掉契约违规
      → resolve_model(None, None, global) 无「项目」一级 → 模板题库降级

缺陷 B（#1463）：_complete() 无幂等
  根因链：
    总纲名 = f"{one_liner[:30]}（书级大纲）"（恒定同名）
      → 第二次 confirm 无条件建总纲 → 撞唯一约束
      → outline_service.py:253-255 raise OutlineNameConflictError
      → API 层未映射 → 500「内部错误（无详情）」

════════════════════════════════════════════════════════════════════
用例分组与预期（RED 阶段；实现者不得改本文件）

【新增契约】描述「修复后应有行为」——当前必须 FAIL：
  A-1 test_project_level_model_reaches_llm_with_uuid_repo
  A-2 test_repo_contract_violation_is_not_swallowed
  B-1 test_second_confirm_reuses_existing_overall_outline
  B-2 test_deterministic_path_complete_is_idempotent
  B-4 test_second_confirm_reuses_existing_protagonist
  B-6 test_conflict_propagates_when_outline_repo_missing
      （未装配查重面 → 无从复用 → 冲突必须原样抛出，不得静默吞）
  B-7 test_outline_conflict_recovers_via_second_lookup
      （并发窗口：查重未命中→创建撞名→二次查名复用）
  B-8 test_character_conflict_propagates_when_character_repo_missing
  B-9 test_character_conflict_recovers_via_second_lookup
  B-10 test_outline_conflict_propagates_when_reread_still_misses
  B-11 test_character_conflict_propagates_when_reread_still_misses
      （「无从复用就响亮失败」的最后一格：二次查名仍取不到 → 原样抛）

【反例守护】描述「修复后不得退化的既有行为」——当前即 PASS，修复后必须保持 PASS：
  A-3 test_no_model_configured_still_degrades_to_templates
      （真未配任何模型 → 仍降级模板题库；收窄 except 不得把这条路径打死）
  A-4 test_unexpected_repo_failure_still_falls_back_to_global
      （非契约类异常（如 DB 抖动）→ 仍回退全局模型；#977 既有语义）
  B-3 test_first_confirm_creates_overall_outline
      （首次 confirm 仍要真的建总纲并回填 root_outline_id）
  B-5 test_first_confirm_creates_protagonist_once
      （首次 confirm 仍要真的建主角并回填 character_ids）
  G-1 test_resolve_model_project_level_non_empty
      （纯函数：项目一级非空时优先于空全局）

⚠️ B-4 的由来（实测发现，见 issue #1463 §影响「同一项目第二次访谈必然 500」）：
  `_complete` 对**两个**养成实体各做一次由会话内容派生的确定性命名 create：
  总纲（`one_liner[:30]` 派生）与主角（`confirmed_items`/q3 派生，无信息时回退字面量「主角」）。
  只修总纲时，第二次 confirm 会前进到主角那一步继续 500（CharacterNameConflictError）。
  「幂等须同时覆盖两者」的「两者」在实现层是**两条调用路径 + 两个实体**，四格都要覆盖。

若某条实际状态与上述预期不符，**如实报告，不要改断言凑数**。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.ports.character_errors import CharacterNameConflictError
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.ports.outline_errors import OutlineNameConflictError
from inkflow.domain.services.model_resolution import resolve_model
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    ROUND2_QUESTIONS,
    PlannerService,
)
from inkflow.infrastructure.database.repositories._id_guard import require_uuid_pk

PID = uuid.UUID(int=1001)
"""项目主键：uuid.UUID(int=n) 形态（仓库惯例，落 SQLite INT64 范围）。"""

ONE_LINER = "写一本关于时间旅者的悬疑小说"
OVERALL_NAME = f"{ONE_LINER[:30]}（书级大纲）"
"""总纲名（planner_service._outline_name）：同项目同一句话 → 恒定同名（#1463 根因）。"""


# ── 桩：真实入参契约（复用真 require_uuid_pk，不自己重写判据） ──────────


class _UuidOnlyProjectRepo:
    """镜像 SQLiteProjectRepository.get 的入参契约。

    关键：判据直接复用生产 guard `require_uuid_pk`——裸 int → TypeError。
    这样本组探针与生产仓储同源，不是「测试自己写一个宽松假 repo」。
    """

    def __init__(self, project: object | None) -> None:
        self._project = project
        self.received: list[object] = []

    async def get(self, project_id: object) -> object | None:
        require_uuid_pk(project_id)  # 裸 int → TypeError（ADR-060 D9）
        self.received.append(project_id)
        return self._project


class _AlwaysTypeErrorRepo:
    """恒抛 TypeError 的 repo：模拟「契约违规被触发」的形态。"""

    async def get(self, project_id: object) -> object | None:
        raise TypeError(
            "require_uuid_pk: 入参必须是 uuid.UUID 或 uuid 字符串，"
            f"得到 {type(project_id).__name__}（调用方不应自行 .int，见 ADR-060 D9）"
        )


class _BoomingRepo:
    """非契约类异常（DB 抖动）——可预期失败，应回退全局而非崩（#977 语义）。"""

    async def get(self, project_id: object) -> object | None:
        raise RuntimeError("db down")


class _NameUniqueOutlineService:
    """镜像 OutlineService.create_outline 的同名冲突语义（outline_service.py:253-255）。"""

    def __init__(self) -> None:
        self.by_name: dict[str, SimpleNamespace] = {}
        self.calls: list[str] = []

    async def __call__(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str,
        level: str,
    ) -> SimpleNamespace:
        self.calls.append(name)
        if name in self.by_name:
            raise OutlineNameConflictError()
        created = SimpleNamespace(id=uuid.uuid4(), name=name, level=level)
        self.by_name[name] = created
        return created


class _OutlineRepoByName:
    """镜像 SQLiteOutlineRepository 的名称查重面（get_by_name / list 两形态均可）。"""

    def __init__(self, service: _NameUniqueOutlineService) -> None:
        self._service = service
        self.name_lookups: list[str] = []

    async def get_by_name(self, project_id: uuid.UUID, name: str) -> object | None:
        require_uuid_pk(project_id)
        self.name_lookups.append(name)
        return self._service.by_name.get(name)

    async def list(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50, **kwargs: object
    ) -> tuple[list[object], int]:
        require_uuid_pk(project_id)
        items = list(self._service.by_name.values())
        return items, len(items)


class _NameUniqueCharacterService:
    """镜像 CharacterService.create_character 的同名冲突语义（character_service.py:166）。"""

    def __init__(self) -> None:
        self.by_name: dict[str, SimpleNamespace] = {}
        self.calls: list[str] = []

    async def __call__(
        self,
        project_id: uuid.UUID,
        name: str,
        extra: dict | None = None,
    ) -> SimpleNamespace:
        self.calls.append(name)
        if name in self.by_name:
            raise CharacterNameConflictError()
        created = SimpleNamespace(id=uuid.uuid4(), name=name)
        self.by_name[name] = created
        return created


class _CharacterRepoByName:
    """镜像 SQLiteCharacterRepository 的名称查重面（get_by_name / list 两形态均可）。"""

    def __init__(self, service: _NameUniqueCharacterService) -> None:
        self._service = service
        self.name_lookups: list[str] = []

    async def get_by_name(self, project_id: uuid.UUID, name: str) -> object | None:
        require_uuid_pk(project_id)
        self.name_lookups.append(name)
        return self._service.by_name.get(name)

    async def list(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50, **kwargs: object
    ) -> tuple[list[object], int]:
        require_uuid_pk(project_id)
        items = list(self._service.by_name.values())
        return items, len(items)


# ── helpers ────────────────────────────────────────────────────────────


def _project_with_model(model: str | None) -> SimpleNamespace:
    return SimpleNamespace(config=ProjectConfig(model=model))


def _book_repo() -> AsyncMock:
    """planner 会话 / 计划仓储鸭子对象。"""
    repo = AsyncMock()
    repo.get_planner_session.return_value = None
    repo.get_writing_plan.return_value = None
    return repo


def _llm_json() -> str:
    """LLM 结构化输出：问题全覆盖必答项（避免触发补问重试），id 与模板题可区分。"""
    questions = [
        {
            "id": "llm-q1",
            "text": "题材：悬疑为主还是混合？",
            "template": "以 ___ 为主",
            "kind": "general",
        },
        {"id": "llm-q2", "text": "篇幅：预计多少字？", "template": "约 ___ 字", "kind": "general"},
        {
            "id": "llm-q3",
            "text": "主题：一句话描述主题？",
            "template": "主题是 ___",
            "kind": "general",
        },
    ]
    return json.dumps(
        {"questions": questions, "confirmed_items": [], "conflicts": []},
        ensure_ascii=False,
    )


def _llm_client() -> AsyncMock:
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content=_llm_json(), model="test")
    return llm


def _outline_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _char_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _make_service(
    *,
    repo: AsyncMock | None = None,
    outline_service: object | None = None,
    outline_repo: object | None = None,
    character_service: object | None = None,
    character_repo: object | None = None,
    llm_client: object | None = None,
    project_repo: object | None = None,
    llm_default_model: str = "",
) -> PlannerService:
    return PlannerService(
        repo=repo or _book_repo(),
        write_auto=AsyncMock(return_value=None),
        outline_service=outline_service or AsyncMock(return_value=_outline_dummy()),
        character_service=character_service or AsyncMock(return_value=_char_dummy()),
        character_repo=character_repo,
        llm_client=llm_client,
        project_context_getter=AsyncMock(return_value="设定摘要：时间旅者，悬疑基调"),
        prompt_manager=None,
        outline_repo=outline_repo,
        project_repo=project_repo,
        llm_default_model=llm_default_model,
    )


def _session(**overrides: object) -> PlannerSession:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": PID,
        "status": "drafting",
        "one_liner": ONE_LINER,
        "round": 2,
        "asked_questions": list(ROUND2_QUESTIONS),
        "answers": {},
        "authorized": [],
        "writing_plan_id": None,
    }
    base.update(overrides)
    return PlannerSession(**base)  # type: ignore[arg-type]  # 测试 helper：dict 展开


@contextmanager
def _capture_loguru(level: str = "WARNING"):
    """loguru sink 捕获（镜像 test_planner_service_977.py 既有形态）。"""
    records: list = []
    sink_id = logger.add(lambda message: records.append(message), level=level)
    try:
        yield records
    finally:
        logger.remove(sink_id)


def _warnings(records: list) -> list:
    return [r for r in records if r.record["level"].name == "WARNING"]


# ══════════════════════════════════════════════════════════════════════
# 缺陷 A（#1462）
# ══════════════════════════════════════════════════════════════════════


async def test_project_level_model_reaches_llm_with_uuid_repo() -> None:
    """【新增契约 A-1】仅配项目级模型（全局为空）→ 走 LLM 动态提问，model=项目模型。

    当前实现传 `project_id.int` → 真实 guard 抛 TypeError → 被吞 → 项目级模型恒空
    → `_generate_questions` 返回 None → chat 从未被调用 → 本用例 FAIL。
    """
    project_repo = _UuidOnlyProjectRepo(_project_with_model("project/model"))
    llm = _llm_client()
    svc = _make_service(llm_client=llm, project_repo=project_repo, llm_default_model="")

    session = await svc.start(PID, ONE_LINER)

    assert project_repo.received == [PID], "repo 入口必须收到领域 UUID（不得自行 .int）"
    assert llm.chat.await_args is not None, "项目级模型非空时必须调 LLM（不得落模板题库）"
    assert llm.chat.await_args.kwargs["model"] == "project/model"
    assert [q["id"] for q in session.asked_questions] == ["llm-q1", "llm-q2", "llm-q3"], (
        "必须走 LLM 动态提问（落 _respond_deterministic 时题面为 ROUND1 模板题）"
    )


async def test_repo_contract_violation_is_not_swallowed() -> None:
    """【新增契约 A-2】契约违规（repo 抛 TypeError）必须冒泡，不得静默降级成「未配置模型」。

    当前 `except Exception: project_model = None` 把 TypeError 吞成「无项目模型」
    → 不抛异常 → 本用例 FAIL。
    """
    svc = _make_service(
        llm_client=_llm_client(),
        project_repo=_AlwaysTypeErrorRepo(),
        llm_default_model="global/model",
    )

    with pytest.raises(TypeError):
        await svc.start(PID, ONE_LINER)


async def test_no_model_configured_still_degrades_to_templates() -> None:
    """【反例守护 A-3】真未配任何模型 → 仍降级模板题库 + 一次 WARN + 不崩。

    收窄 except 时必须保留这条合法降级路径（不得因「不吞异常」把无模型场景打死）。
    """
    project_repo = _UuidOnlyProjectRepo(_project_with_model(None))
    llm = _llm_client()
    svc = _make_service(llm_client=llm, project_repo=project_repo, llm_default_model="")

    with _capture_loguru("WARNING") as records:
        session = await svc.start(PID, ONE_LINER)

    llm.chat.assert_not_awaited()
    warns = _warnings(records)
    assert len(warns) == 1
    assert "未配置默认模型，访谈使用模板题库" in warns[0].record["message"]
    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]


async def test_unexpected_repo_failure_still_falls_back_to_global() -> None:
    """【反例守护 A-4】非契约类异常（DB 抖动 RuntimeError）→ 仍回退全局模型（#977 语义）。

    反过度修正锚：收窄 except 只允许对「契约违规」响亮失败，可预期故障仍须降级。
    """
    llm = _llm_client()
    svc = _make_service(
        llm_client=llm,
        project_repo=_BoomingRepo(),
        llm_default_model="global/model",
    )

    with _capture_loguru("WARNING") as records:
        await svc.start(PID, ONE_LINER)

    assert _warnings(records) == []
    assert llm.chat.await_args is not None
    assert llm.chat.await_args.kwargs["model"] == "global/model"


def test_resolve_model_project_level_non_empty() -> None:
    """【守护 G-1】纯函数：项目一级非空即用（全局为空也取项目模型）。"""
    assert resolve_model(None, "project/model", "") == "project/model"
    assert resolve_model(None, "project/model", "global/model") == "project/model"
    assert resolve_model(None, None, "global/model") == "global/model"
    assert resolve_model(None, None, "") is None


# ══════════════════════════════════════════════════════════════════════
# 缺陷 B（#1463）
# ══════════════════════════════════════════════════════════════════════


async def test_first_confirm_creates_overall_outline() -> None:
    """【反例守护 B-3】首次 confirm（无既有同名总纲）→ 仍要建总纲并回填 root_outline_id。"""
    outline_svc = _NameUniqueOutlineService()
    outline_repo = _OutlineRepoByName(outline_svc)
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(repo=repo, outline_service=outline_svc, outline_repo=outline_repo)

    result = await svc.respond(session.id, {}, confirm=True)

    assert result.completed is True
    assert outline_svc.calls == [OVERALL_NAME]
    assert result.writing_plan is not None
    assert result.writing_plan.root_outline_id == outline_svc.by_name[OVERALL_NAME].id


async def test_second_confirm_reuses_existing_overall_outline() -> None:
    """【新增契约 B-1】同一项目第二次 confirm（同名总纲已落库）→ 复用既有总纲，不抛。

    当前 `_complete` 无条件建总纲 → 第二次撞唯一约束 → `OutlineNameConflictError`
    → 本用例 FAIL（复现 #1463「重试即永久失败」）。
    """
    outline_svc = _NameUniqueOutlineService()
    outline_repo = _OutlineRepoByName(outline_svc)
    repo = _book_repo()

    first = _session(confirming=True)
    repo.get_planner_session.return_value = first
    svc = _make_service(repo=repo, outline_service=outline_svc, outline_repo=outline_repo)
    result1 = await svc.respond(first.id, {}, confirm=True)

    second = _session(confirming=True)
    repo.get_planner_session.return_value = second
    result2 = await svc.respond(second.id, {}, confirm=True)  # 当前抛 OutlineNameConflictError

    created_id = outline_svc.by_name[OVERALL_NAME].id
    assert outline_svc.calls == [OVERALL_NAME], "同名总纲只允许创建一次（第二次必须复用）"
    assert result1.writing_plan is not None and result1.writing_plan.root_outline_id == created_id
    assert result2.completed is True
    assert result2.writing_plan is not None
    assert result2.writing_plan.root_outline_id == created_id


async def test_deterministic_path_complete_is_idempotent() -> None:
    """【新增契约 B-2】确定性降级路径（llm_client=None）的 _complete 同样幂等。

    `_complete` 被两条路径调用（LLM confirm 与确定性降级）——幂等必须同时覆盖两者；
    总纲与主角两次 create 都要幂等。
    """
    outline_svc = _NameUniqueOutlineService()
    outline_repo = _OutlineRepoByName(outline_svc)
    char_svc = _NameUniqueCharacterService()
    char_repo = _CharacterRepoByName(char_svc)
    repo = _book_repo()
    answers = {"q1": "悬疑", "q2": "约 30 万字", "q3": "主题是时间悖论", "q4": "3 卷", "q5": "2 个"}

    first = _session(round=2, answers=dict(answers))
    repo.get_planner_session.return_value = first
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=outline_repo,
        character_service=char_svc,
        character_repo=char_repo,
        llm_client=None,
    )
    result1 = await svc.respond(first.id, {})

    second = _session(round=2, answers=dict(answers))
    repo.get_planner_session.return_value = second
    result2 = await svc.respond(second.id, {})  # 当前抛 OutlineNameConflictError

    created_id = outline_svc.by_name[OVERALL_NAME].id
    assert result1.completed is True
    assert outline_svc.calls == [OVERALL_NAME]
    assert result2.completed is True
    assert result2.writing_plan is not None
    assert result2.writing_plan.root_outline_id == created_id
    assert char_svc.calls == ["主角"], "同名主角只允许创建一次（第二次必须复用）"
    assert result2.writing_plan.character_ids == [char_svc.by_name["主角"].id]


async def test_first_confirm_creates_protagonist_once() -> None:
    """【反例守护 B-5】首次 confirm → 主角必须真的建一次并回填 character_ids。"""
    outline_svc = _NameUniqueOutlineService()
    char_svc = _NameUniqueCharacterService()
    char_repo = _CharacterRepoByName(char_svc)
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_OutlineRepoByName(outline_svc),
        character_service=char_svc,
        character_repo=char_repo,
    )

    result = await svc.respond(session.id, {}, confirm=True)

    assert char_svc.calls == ["主角"]
    assert result.writing_plan is not None
    assert result.writing_plan.character_ids == [char_svc.by_name["主角"].id]


async def test_second_confirm_reuses_existing_protagonist() -> None:
    """【新增契约 B-4】同一项目第二次 confirm → 复用既有主角（同名角色唯一约束同样不可撞）。

    `_complete` 对两个养成实体（总纲 + 主角）各有一个由会话内容派生的确定性名字；
    只修总纲时第二次 confirm 会改为撞 `CharacterNameConflictError` → 用户仍无法完成访谈
    （正是 issue #1463「同一项目第二次访谈必然 500」的另一半）。
    """
    outline_svc = _NameUniqueOutlineService()
    char_svc = _NameUniqueCharacterService()
    char_repo = _CharacterRepoByName(char_svc)
    repo = _book_repo()

    first = _session(confirming=True)
    repo.get_planner_session.return_value = first
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_OutlineRepoByName(outline_svc),
        character_service=char_svc,
        character_repo=char_repo,
    )
    result1 = await svc.respond(first.id, {}, confirm=True)

    second = _session(confirming=True)
    repo.get_planner_session.return_value = second
    result2 = await svc.respond(second.id, {}, confirm=True)  # 当前抛 CharacterNameConflictError

    created_id = char_svc.by_name["主角"].id
    assert char_svc.calls == ["主角"], "同名主角只允许创建一次（第二次必须复用）"
    assert result1.writing_plan is not None and result1.writing_plan.character_ids == [created_id]
    assert result2.completed is True
    assert result2.writing_plan is not None
    assert result2.writing_plan.character_ids == [created_id]


class _MissOnceRepo:
    """名称查重面：**首次**查名返回 None（模拟「查重后、落库前被别人抢先建好」的并发窗口），
    之后返回真实行——用于锁定「撞名 → 二次查名复用」这条恢复路径。"""

    def __init__(self, by_name: dict) -> None:
        self._by_name = by_name
        self._missed = False

    async def get_by_name(self, project_id: uuid.UUID, name: str) -> object | None:
        require_uuid_pk(project_id)
        if not self._missed:
            self._missed = True
            return None
        return self._by_name.get(name)

    async def list(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50, **kwargs: object
    ) -> tuple[list[object], int]:
        require_uuid_pk(project_id)
        items = list(self._by_name.values())
        return items, len(items)


async def test_conflict_propagates_when_outline_repo_missing() -> None:
    """【新增契约 B-6】未装配 outline_repo（无处复用）→ 同名冲突必须原样抛出。

    守护「不得静默吞掉业务冲突」：无从复用就响亮失败，由 API 层映射 4xx + detail。
    """
    outline_svc = _NameUniqueOutlineService()
    outline_svc.by_name[OVERALL_NAME] = SimpleNamespace(
        id=uuid.uuid4(), name=OVERALL_NAME, level="overall"
    )
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(repo=repo, outline_service=outline_svc, outline_repo=None)

    with pytest.raises(OutlineNameConflictError):
        await svc.respond(session.id, {}, confirm=True)


async def test_outline_conflict_recovers_via_second_lookup() -> None:
    """【新增契约 B-7】并发窗口：查重未命中 → 创建撞名 → 二次查名命中 → 复用既有总纲。"""
    outline_svc = _NameUniqueOutlineService()
    existing = SimpleNamespace(id=uuid.uuid4(), name=OVERALL_NAME, level="overall")
    outline_svc.by_name[OVERALL_NAME] = existing
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_MissOnceRepo(outline_svc.by_name),
    )

    result = await svc.respond(session.id, {}, confirm=True)

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.root_outline_id == existing.id


async def test_character_conflict_propagates_when_character_repo_missing() -> None:
    """【新增契约 B-8】未装配 character_repo（无处复用）→ 主角同名冲突必须原样抛出。

    反例守护：不得把「主角已存在」静默降级成「本次不建主角」（那正是 #1462 家族
    「静默吞掉契约/业务异常」的复发形态）。
    """
    outline_svc = _NameUniqueOutlineService()
    char_svc = _NameUniqueCharacterService()
    char_svc.by_name["主角"] = SimpleNamespace(id=uuid.uuid4(), name="主角")
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_OutlineRepoByName(outline_svc),
        character_service=char_svc,
        character_repo=None,
    )

    with pytest.raises(CharacterNameConflictError):
        await svc.respond(session.id, {}, confirm=True)


async def test_character_conflict_recovers_via_second_lookup() -> None:
    """【新增契约 B-9】并发窗口：主角查重未命中 → 创建撞名 → 二次查名命中 → 复用既有主角。"""
    outline_svc = _NameUniqueOutlineService()
    char_svc = _NameUniqueCharacterService()
    existing = SimpleNamespace(id=uuid.uuid4(), name="主角")
    char_svc.by_name["主角"] = existing
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_OutlineRepoByName(outline_svc),
        character_service=char_svc,
        character_repo=_MissOnceRepo(char_svc.by_name),
    )

    result = await svc.respond(session.id, {}, confirm=True)

    assert result.completed is True
    assert result.writing_plan is not None
    assert result.writing_plan.character_ids == [existing.id]


class _NoNameRepo:
    """名称查重面**恒返回 None**（模拟「创建撞名后二次查名仍取不到」的退化形态）。"""

    async def get_by_name(self, project_id: uuid.UUID, name: str) -> object | None:
        require_uuid_pk(project_id)
        return None

    async def list(
        self, project_id: uuid.UUID, offset: int = 0, limit: int = 50, **kwargs: object
    ) -> tuple[list[object], int]:
        require_uuid_pk(project_id)
        return [], 0


async def test_outline_conflict_propagates_when_reread_still_misses() -> None:
    """【新增契约 B-10】查重未命中 → 创建撞名 → 二次查名**仍取不到** → 原样抛出。

    锁定「无从复用就响亮失败」的最后一格（不得返回 completed=True 而静默丢结构锚点）。
    """
    outline_svc = _NameUniqueOutlineService()
    outline_svc.by_name[OVERALL_NAME] = SimpleNamespace(
        id=uuid.uuid4(), name=OVERALL_NAME, level="overall"
    )
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(repo=repo, outline_service=outline_svc, outline_repo=_NoNameRepo())

    with pytest.raises(OutlineNameConflictError):
        await svc.respond(session.id, {}, confirm=True)


async def test_character_conflict_propagates_when_reread_still_misses() -> None:
    """【新增契约 B-11】主角同名冲突 + 二次查名仍取不到 → 原样抛出（不得静默丢主角）。"""
    outline_svc = _NameUniqueOutlineService()
    char_svc = _NameUniqueCharacterService()
    char_svc.by_name["主角"] = SimpleNamespace(id=uuid.uuid4(), name="主角")
    repo = _book_repo()
    session = _session(confirming=True)
    repo.get_planner_session.return_value = session
    svc = _make_service(
        repo=repo,
        outline_service=outline_svc,
        outline_repo=_OutlineRepoByName(outline_svc),
        character_service=char_svc,
        character_repo=_NoNameRepo(),
    )

    with pytest.raises(CharacterNameConflictError):
        await svc.respond(session.id, {}, confirm=True)
