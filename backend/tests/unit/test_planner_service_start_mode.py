"""#544 书级编排项目可选 + 起点模板 —— PlannerService.start 起点模式
契约测试（TDD RED 阶段，兄弟文件）。

权威来源：issue #544（书级编排项目可选 + 起点模板 new/continue/branch）。
本文件为 `domain/services/planner_service.py`（MODIFY）的
start(mode/source_outline_id) 扩展 + 分支章复制定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【start 签名扩展】
   async def start(self, project_id, one_liner, mode: str = "new",
                   source_outline_id: uuid.UUID | None = None) -> PlannerSession
   - 校验：mode 不在 {new, continue, branch} →
     ValueError("不支持的起点模式: {mode}")
   - mode==branch 且 source_outline_id 为 None →
     ValueError("分支起点需要源大纲")

2. 【PlannerSession / WritingPlan 新字段】（默认值向后兼容）
   - start_type: str = "new"
   - source_outline_id: uuid.UUID | None = None
   - copied_outline_id: uuid.UUID | None = None
     （#544 命名裁定：源大纲 id 存 source_outline_id；分支复制出的
     新根 id 存 copied_outline_id，避免语义混淆）

3. 【构造扩展】PlannerService 构造新增可选参数 outline_repo
   （鸭子：async get(id)、async list(project_id, offset=0, limit=50)
   -> (items, total)，镜像 SQLiteOutlineRepository 形态）。

4. 【分支章复制契约】（mode="branch" + source_outline_id）
   - outline_repo.get(source_outline_id) → None → ValueError("源大纲不存在")
   - outline_repo.list(project_id) 取项目全部大纲，按 parent_id 链收集
     source 根及其所有后代（无关大纲不复制）
   - 每个节点经注入的 outline_service（可调用 create_outline）复制一份：
     新根 name = 原名 + "（分支）"，level/description/sort_order 原样；
     子节点 parent_id 映射到新父 id
   - session.start_type="branch"、copied_outline_id=新根 id

5. 【continue 契约】（mode="continue" + source_outline_id）
   - 不复制大纲；session.start_type="continue"、
     session.source_outline_id=source_outline_id
   - _complete() 构造 WritingPlan 时透传 start_type/source_outline_id/
     copied_outline_id；continue 时 root_outline_id=source_outline_id

6. 【RED 预期形态】PlannerService 构造无 outline_repo 参数 → TypeError
   （既有实现）；start() 不接受 mode kwarg → TypeError；PlannerSession /
   WritingPlan 无新字段 → AttributeError。既有用例保持全绿（新参数/
   字段默认 None 向后兼容）。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.services.planner_service import ROUND1_QUESTIONS, PlannerService


def _sid() -> uuid.UUID:
    return uuid.uuid4()


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _session(**overrides) -> PlannerSession:
    base = dict(
        id=_sid(),
        project_id=_pid(),
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=list(ROUND1_QUESTIONS),
        answers={},
        authorized=[],
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return PlannerSession(**base)


def _make_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_planner_session.return_value = None
    repo.get_writing_plan.return_value = None
    return repo


def _outline_dummy():
    return SimpleNamespace(id=uuid.uuid4())


class _FakeOutlineRepo:
    """鸭子 outline_repo（#544）：async get / async list -> (items, total)。

    镜像 SQLiteOutlineRepository 形态：list 返回 (items, total) 二元组。
    """

    def __init__(self, outlines: list[Outline]) -> None:
        self._by_id = {o.id: o for o in outlines}

    async def get(self, outline_id: uuid.UUID) -> Outline | None:
        return self._by_id.get(outline_id)

    async def list(self, project_id, offset: int = 0, limit: int = 50):
        items = list(self._by_id.values())
        return items, len(items)


def _outline_tree() -> tuple[Outline, Outline, Outline, Outline]:
    """分支复制源树：根（volume）+ 2 子（chapter，parent 指向根）+ 1 无关大纲。"""
    now = datetime.now(UTC)
    pid = _pid()
    root = Outline(
        id=uuid.uuid4(),
        project_id=pid,
        name="第一卷 雾都疑云",
        description="第一卷：开局悬案",
        sort_order=1,
        level="volume",
        parent_id=None,
        created_at=now,
        updated_at=now,
    )
    child1 = Outline(
        id=uuid.uuid4(),
        project_id=pid,
        name="第一章 雨夜来客",
        description="第一章：命案发生",
        sort_order=1,
        level="chapter",
        parent_id=root.id,
        created_at=now,
        updated_at=now,
    )
    child2 = Outline(
        id=uuid.uuid4(),
        project_id=pid,
        name="第二章 时间旅者",
        description="第二章：穿越伏笔",
        sort_order=2,
        level="chapter",
        parent_id=root.id,
        created_at=now,
        updated_at=now,
    )
    other = Outline(
        id=uuid.uuid4(),
        project_id=pid,
        name="另一棵大纲",
        description="无关大纲",
        sort_order=9,
        level="volume",
        parent_id=None,
        created_at=now,
        updated_at=now,
    )
    return root, child1, child2, other


def _make_service(
    repo: AsyncMock,
    *,
    outline_repo: _FakeOutlineRepo | None = None,
    outline_service: AsyncMock | None = None,
) -> PlannerService:
    """装配 PlannerService（outline_repo/outline_service 可选注入）。

    outline_service=None 时完成路径跳过落库（仅测试隔离用，同既有形态）；
    outline_repo 仅在传入时透传——RED 期让不涉及分支复制的用例先撞
    start(mode=...) TypeError / 模型字段 AttributeError（更精确的失败形态）。
    """
    kwargs: dict = dict(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=outline_service,
        character_service=None,
    )
    if outline_repo is not None:
        kwargs["outline_repo"] = outline_repo
    return PlannerService(**kwargs)


# ── start：mode 缺省 = new（#544）──────────────────────────────────


@pytest.mark.asyncio
async def test_start_default_mode_new():
    """start(mode 缺省) → session.start_type=="new"、source_outline_id=None；
    outline_service 未被调用（不复制）。"""
    repo = _make_repo()
    outline_service = AsyncMock(return_value=_outline_dummy())
    svc = _make_service(repo, outline_service=outline_service)

    session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert session.start_type == "new"
    assert session.source_outline_id is None
    outline_service.assert_not_awaited()


# ── start：branch 章复制（#544）────────────────────────────────────


@pytest.mark.asyncio
async def test_start_branch_mode_copies_outline_tree():
    """branch + 源大纲 → 复制根及其后代共 3 次调用（无关大纲不复制）；
    子节点 parent_id 映射到新根 id；session.start_type=="branch"、
    copied_outline_id==新根 id。"""
    repo = _make_repo()
    root, child1, child2, _other = _outline_tree()
    outline_repo = _FakeOutlineRepo([root, child1, child2, _other])
    new_root_id, new_child1_id, new_child2_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    outline_service = AsyncMock(
        side_effect=[
            SimpleNamespace(id=new_root_id),
            SimpleNamespace(id=new_child1_id),
            SimpleNamespace(id=new_child2_id),
        ]
    )
    svc = _make_service(
        repo, outline_repo=outline_repo, outline_service=outline_service
    )

    session = await svc.start(
        _pid(), "写一本关于时间旅者的悬疑小说", mode="branch", source_outline_id=root.id
    )

    calls = outline_service.await_args_list
    assert len(calls) == 3  # 根 + 2 子；无关大纲 _other 不复制
    # 新根：原名 + "（分支）"，level/description/sort_order 原样，parent_id=None
    assert calls[0].kwargs.get("name") == f"{root.name}（分支）"
    assert calls[0].kwargs.get("level") == root.level
    assert calls[0].kwargs.get("description") == root.description
    assert calls[0].kwargs.get("sort_order") == root.sort_order
    assert calls[0].kwargs.get("parent_id") is None
    # 子节点：parent_id 映射到新根 id，name/level/sort_order 原样
    assert calls[1].kwargs.get("parent_id") == new_root_id
    assert calls[1].kwargs.get("name") == child1.name
    assert calls[1].kwargs.get("level") == child1.level
    assert calls[1].kwargs.get("sort_order") == child1.sort_order
    assert calls[2].kwargs.get("parent_id") == new_root_id
    assert session.start_type == "branch"
    assert session.copied_outline_id == new_root_id


@pytest.mark.asyncio
async def test_start_branch_missing_source_raises():
    """branch 缺 source_outline_id → ValueError("分支起点需要源大纲")。"""
    svc = _make_service(_make_repo())

    with pytest.raises(ValueError, match="分支起点需要源大纲"):
        await svc.start(_pid(), "写一本关于时间旅者的悬疑小说", mode="branch")


@pytest.mark.asyncio
async def test_start_branch_source_not_found_raises():
    """branch + 源大纲不存在 → ValueError("源大纲不存在")。"""
    svc = _make_service(_make_repo(), outline_repo=_FakeOutlineRepo([]))

    with pytest.raises(ValueError, match="源大纲不存在"):
        await svc.start(
            _pid(), "写一本关于时间旅者的悬疑小说", mode="branch", source_outline_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_start_branch_outline_repo_missing_raises():
    """branch + 源大纲非空但 outline_repo 未装配 → ValueError("源大纲不存在")
    （#544 coverage 补测）。"""
    svc = _make_service(_make_repo())  # 未注入 outline_repo

    with pytest.raises(ValueError, match="源大纲不存在"):
        await svc.start(
            _pid(), "写一本关于时间旅者的悬疑小说", mode="branch", source_outline_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_start_branch_outline_service_missing_raises():
    """branch + outline_repo 就绪但 outline_service 未装配 → ValueError("分支复制未装配大纲服务")
    （#544 coverage 补测）。"""
    root, _child1, _child2, _other = _outline_tree()
    svc = _make_service(
        _make_repo(), outline_repo=_FakeOutlineRepo([root]), outline_service=None
    )

    with pytest.raises(ValueError, match="分支复制未装配大纲服务"):
        await svc.start(
            _pid(), "写一本关于时间旅者的悬疑小说", mode="branch", source_outline_id=root.id
        )


# ── start：continue（#544）─────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_continue_mode_no_copy():
    """continue + 源大纲 → 不复制；session.start_type=="continue"、
    source_outline_id 原样。"""
    repo = _make_repo()
    outline_service = AsyncMock(return_value=_outline_dummy())
    svc = _make_service(repo, outline_service=outline_service)
    oid = uuid.uuid4()

    session = await svc.start(
        _pid(), "写一本关于时间旅者的悬疑小说", mode="continue", source_outline_id=oid
    )

    assert session.start_type == "continue"
    assert session.source_outline_id == oid
    outline_service.assert_not_awaited()


# ── start：非法 mode 校验（#544）───────────────────────────────────


@pytest.mark.asyncio
async def test_start_invalid_mode_raises():
    """非法 mode → ValueError("不支持的起点模式")。"""
    svc = _make_service(_make_repo())

    with pytest.raises(ValueError, match="不支持的起点模式"):
        await svc.start(_pid(), "写一本关于时间旅者的悬疑小说", mode="xxx")


# ── _complete：WritingPlan 透传（#544）─────────────────────────────


@pytest.mark.asyncio
async def test_respond_confirm_complete_passthrough_continue():
    """continue 完成路径（confirm）→ WritingPlan 透传 start_type/
    source_outline_id/copied_outline_id，root_outline_id=source_outline_id。"""
    repo = _make_repo()
    oid = uuid.uuid4()
    session = _session(
        confirming=True,
        start_type="continue",
        source_outline_id=oid,
    )
    repo.get_planner_session.return_value = session
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=None,
        character_service=None,
    )

    result = await svc.respond(session.id, {}, confirm=True)

    assert result.completed is True
    plan = result.writing_plan
    assert plan is not None
    assert plan.start_type == "continue"
    assert plan.source_outline_id == oid
    assert plan.copied_outline_id is None
    assert plan.root_outline_id == oid
