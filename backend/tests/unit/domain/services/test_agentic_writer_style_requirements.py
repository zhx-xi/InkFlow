"""agentic 单章轨 · writing_style / writing_requirements 消费契约 — RED（#1231 + #1232）。

同族参照（**照抄，不另造**）：
- style 消费语义 = F3 轨 `writing_service.py:66`
  ``style = request.style_hint or project.config.writing_style or ""``
- 项目配置来源 = book 轨 `resolve_brief_setting(project_config=...)`
  （`chapter_brief.py` W1-A 建立的唯一配置读取点）
- 章级要求搬运 = book 轨 W2-A4 `chapter_requirements_getter` 回调
  （`book_service.py:155` + `api/routers/books.py:423`，PR #1205）

契约（GREEN 必须满足）
---------------------
1. `AgenticWriterService` 构造新增**两个可选依赖**（与 `BookService` 同名同形，机制统一）：
   - `project_config_getter: Callable[[uuid.UUID], Awaitable[object | None]] | None`
   - `chapter_requirements_getter: Callable[[uuid.UUID], Awaitable[str | None]] | None`
2. `_build_initial_message` 消费二者（真值来自**真实 repo / 真实列**，非手工构造 extra）：
   - **#1231**：`style_hint` 为空 → 回退 `config.writing_style`；
     两者皆空 → **不注入风格段**（反向断言）。
   - **#1232**：`writing_requirements` 取 `chapters.writing_requirements` **列值**；
     列值优先于入参 `--outline`（不覆盖）。
3. `AgenticWriteRequest` 新增 `writing_requirements: str | None = None`
   （入参通道；None = 未传 → 走列值 / 不注入）。

可证伪性
--------
- 把 `project_config_getter` 传 None → 断言 1（style）必 FAIL；
- 把 `chapter_requirements_getter` 传 None → 断言 2（列值）必 FAIL；
- 两条各配「不装配 → 值必不出现」的反向用例。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from inkflow.domain.models.agent_run import AgenticWriteRequest
from inkflow.domain.services.agentic_writer_service import AgenticWriterService

# ── fixture 锚点值（真实可辨识，与实现硬编码字面量不同源）─────────────

PROJECT_ID = uuid.UUID("0199a000-0000-7000-8000-000000000001")
CHAPTER_ID = uuid.UUID("0199a000-0000-7000-8000-000000000002")

REAL_STYLE = "紫电青霜九转玄冰探针风格标记"
REAL_COLUMN_REQUIREMENT = "本章须体现「替师出诊」的义务感：先问诊后论武，对话占比过半"
OUTLINE_TEXT = "【探针】本章大纲：观测章级要求注入"
DEFAULT_STYLE_HINT = "遵循项目写作风格与用户偏好（偏好优先于通用文风）。"


def _history(*messages: dict) -> dict:
    return {"messages": list(messages)}


def _ai_msg(content: str = "") -> dict:
    return {"type": "ai", "content": content}


class FakeAgent:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.messages: list[Any] = []

    async def invoke(self, messages, config=None):  # 鸭子类型契约
        self.messages.append(messages)
        if self._responses:
            return self._responses.pop(0)
        return _history(_ai_msg("正文"))


def _make_request(**overrides) -> AgenticWriteRequest:
    kwargs: dict[str, Any] = dict(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        outline=OUTLINE_TEXT,
        min_words=2000,
    )
    kwargs.update(overrides)
    return AgenticWriteRequest(**kwargs)


def _make_service(
    *,
    project_config_getter=None,
    chapter_requirements_getter=None,
    responses: list[dict] | None = None,
) -> tuple[AgenticWriterService, FakeAgent]:
    """构造服务（新依赖缺省 None → RED 期既有构造形态仍可跑）."""
    from unittest.mock import AsyncMock

    agent = FakeAgent(responses if responses is not None else [_history(_ai_msg("正文"))])
    service = AgenticWriterService(
        agent_factory=lambda request: agent,
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        run_repo=AsyncMock(),
        chapter_service=AsyncMock(),
        project_config_getter=project_config_getter,
        chapter_requirements_getter=chapter_requirements_getter,
    )
    return service, agent


def _config_with_style(style: str) -> SimpleNamespace:
    """项目配置（ProjectConfig 同形：config 具 writing_style 属性）."""
    return SimpleNamespace(config=SimpleNamespace(writing_style=style))


def _first_user_message(agent: FakeAgent) -> str:
    """取 agent 收到的首条 user 消息文本（真实进 prompt 的面）."""
    assert agent.messages, "agent 未被调用"
    messages = agent.messages[0]
    for message in messages:
        if isinstance(message, dict) and message.get("type") == "user":
            return str(message.get("content", ""))
    raise AssertionError("首条 user 消息缺失")


# ── 契约 1（#1231）：project.config.writing_style 进 prompt ──────────


async def test_project_writing_style_reaches_agentic_prompt() -> None:
    """#1231：`project.config.writing_style` 非空 → 出现在 agentic 单章轨 prompt.

    可证伪性：`project_config_getter=None` → 值取不到 → 断言必 FAIL（下一用例）。
    """

    async def _config_getter(pid: uuid.UUID) -> object | None:
        assert pid == PROJECT_ID
        return _config_with_style(REAL_STYLE)

    service, agent = _make_service(project_config_getter=_config_getter)
    await service.run(_make_request())

    prompt = _first_user_message(agent)
    assert REAL_STYLE in prompt


async def test_writing_style_absent_when_not_configured() -> None:
    """#1231 反向：未装配 config getter / 配置为空 → 不出现 style 实值，且不报错.

    可证伪性：若实现把常量祈使句之外的**实值**注入，本用例必 FAIL。
    """

    async def _empty_config_getter(pid: uuid.UUID) -> object | None:
        return _config_with_style("")

    service, agent = _make_service(project_config_getter=_empty_config_getter)
    await service.run(_make_request())
    assert REAL_STYLE not in _first_user_message(agent)

    # 完全未装配 → 同样不出现（降级不抛错）
    service2, agent2 = _make_service(project_config_getter=None)
    await service2.run(_make_request())
    assert REAL_STYLE not in _first_user_message(agent2)


async def test_explicit_style_hint_wins_over_project_style() -> None:
    """#1231 优先级：`request.style_hint` 显式传入 → 优先于 config（对齐 F3 轨）."""

    async def _config_getter(pid: uuid.UUID) -> object | None:
        return _config_with_style(REAL_STYLE)

    explicit = "显式风格提示探针"
    service, agent = _make_service(project_config_getter=_config_getter)
    await service.run(_make_request(style_hint=explicit))

    prompt = _first_user_message(agent)
    assert explicit in prompt
    assert REAL_STYLE not in prompt


# ── 契约 2（#1232）：chapters 列值进 prompt，且优先于 --outline ─────


async def test_chapter_column_requirements_reaches_agentic_prompt() -> None:
    """#1232：`chapters.writing_requirements` 列值 → 进 agentic prompt.

    可证伪性：`chapter_requirements_getter=None` → 列值取不到 → 断言必 FAIL。
    """

    async def _req_getter(cid: uuid.UUID) -> str | None:
        assert cid == CHAPTER_ID
        return REAL_COLUMN_REQUIREMENT

    service, agent = _make_service(chapter_requirements_getter=_req_getter)
    await service.run(_make_request(writing_requirements=OUTLINE_TEXT))

    prompt = _first_user_message(agent)
    assert REAL_COLUMN_REQUIREMENT in prompt


async def test_chapter_column_takes_precedence_over_request_value() -> None:
    """#1232 优先级：列值 > 入参（`--outline` 复用值不覆盖真实列值）.

    可证伪性：不装配 getter → 入参值不被列值替换（本用例断言必 FAIL）。
    """

    async def _req_getter(cid: uuid.UUID) -> str | None:
        return REAL_COLUMN_REQUIREMENT

    injected = "【#1232 探针】入参 requirements"
    service, agent = _make_service(chapter_requirements_getter=_req_getter)
    await service.run(_make_request(writing_requirements=injected))

    prompt = _first_user_message(agent)
    assert REAL_COLUMN_REQUIREMENT in prompt
    assert injected not in prompt


async def test_requirements_falls_back_to_request_when_column_empty() -> None:
    """#1232 回退：列值为空 → 回退入参值（不报错）；两者皆空 → 不注入."""

    async def _empty_getter(cid: uuid.UUID) -> str | None:
        return None

    injected = "入参兜底探针要求"
    service, agent = _make_service(chapter_requirements_getter=_empty_getter)
    await service.run(_make_request(writing_requirements=injected))
    assert injected in _first_user_message(agent)

    service2, agent2 = _make_service(chapter_requirements_getter=None)
    await service2.run(_make_request())
    assert REAL_COLUMN_REQUIREMENT not in _first_user_message(agent2)


# ── 契约 3（#1232 CLI 根因）：CLI 不再用 --outline 冒充章级要求 ─────


async def test_cli_fetch_chapter_requirements_reads_real_column() -> None:
    """#1232 CLI 侧：`_fetch_chapter_requirements` 取列真实值（非 --outline）.

    可证伪性：把返回体里的列值去掉 → 函数返回空串，断言必 FAIL。
    """
    from inkflow.cli.commands.write import _fetch_chapter_requirements

    class _FakeClient:
        def __init__(self, payload):  # 测试替身
            self.payload = payload

        async def get(self, path: str):  # 测试替身
            return self.payload

    wired = await _fetch_chapter_requirements(
        _FakeClient({"writing_requirements": REAL_COLUMN_REQUIREMENT}), str(CHAPTER_ID)
    )
    assert wired == REAL_COLUMN_REQUIREMENT

    # 列空 / 列缺失 → 空串（调用方回退旗标）
    assert await _fetch_chapter_requirements(_FakeClient({}), str(CHAPTER_ID)) == ""
    assert (
        await _fetch_chapter_requirements(
            _FakeClient({"writing_requirements": None}), str(CHAPTER_ID)
        )
        == ""
    )


async def test_cli_fetch_chapter_requirements_survives_upstream_error() -> None:
    """CLI 取列失败（内核/网络异常）→ 空串且不抛错（观测失败不阻断写作主路径）."""
    from inkflow.cli.commands.write import _fetch_chapter_requirements

    class _BrokenClient:
        async def get(self, path: str):  # 测试替身
            raise RuntimeError("kernel down")

    assert await _fetch_chapter_requirements(_BrokenClient(), str(CHAPTER_ID)) == ""


# ── 契约 4（#1231 + #1232 同源）：真实 repo / 真实列值走通 ────────────

#: InkFlow 主键惯例：DB int64 ↔ uuid.UUID(int=...)。**禁用 uuid4()** ——
#: uuid4().int 溢出 SQLite INTEGER（ai-traps 已知族），故用递增小整数造 id。
_ID_SEQ = iter(range(20_000, 30_000))


def _db_uid() -> uuid.UUID:
    """递增小整数 UUID（可安全往返 SQLite INTEGER 主键）."""
    return uuid.UUID(int=next(_ID_SEQ))


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（启用 FK）——镜像 W2-A4 同层 fixture 形态."""
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import inkflow.infrastructure.database.models  # noqa: F401  # 注册全部 ORM
    from inkflow.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # fixture 回调签名
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_real_repo_column_reaches_agentic_prompt_via_assembly(db_session) -> None:
    """#1231+#1232 同源断言：真实 `chapters` 列值 + 真实 `projects` 配置 → 进 prompt.

    可证伪性：不装配两个 getter → 两值皆不出现（证明断言来自真实数据源）。
    """
    from inkflow.domain.models.chapter import Chapter
    from inkflow.infrastructure.database.models.project import ProjectORM
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )
    from inkflow.infrastructure.database.repositories.project_repo import (
        SQLiteProjectRepository,
    )

    pid = _db_uid()
    db_session.add(ProjectORM(id=pid.int, name="项目"))
    await db_session.commit()

    chapter_repo = SQLiteChapterRepository(db_session)
    created = await chapter_repo.add_chapter(
        Chapter(
            id=_db_uid(),
            project_id=pid,
            title="第一章",
            writing_requirements=REAL_COLUMN_REQUIREMENT,
        )
    )
    project = await SQLiteProjectRepository(db_session).get(pid)
    assert project is not None
    # 显式写入项目风格（不假设默认值非空），经 repo 回读证明真落在库
    project.config.writing_style = REAL_STYLE
    await SQLiteProjectRepository(db_session).update(project)
    reread = await SQLiteProjectRepository(db_session).get(pid)
    style = reread.config.writing_style if reread is not None else ""
    assert style == REAL_STYLE, "项目风格应经 repo 落库并回读一致"

    async def _config_getter(project_id: uuid.UUID) -> object | None:
        proj = await SQLiteProjectRepository(db_session).get(project_id)
        return getattr(proj, "config", None) if proj is not None else None

    async def _req_getter(chapter_id: uuid.UUID) -> str | None:
        chapter = await chapter_repo.get_chapter(chapter_id)
        value = getattr(chapter, "writing_requirements", None) if chapter else None
        return value if isinstance(value, str) and value else None

    # 正向：真实数据源 → prompt
    wired, wired_agent = _make_service(
        project_config_getter=_config_getter, chapter_requirements_getter=_req_getter
    )
    await wired.run(
        _make_request(
            project_id=pid, chapter_id=created.id, writing_requirements="【--outline 复用值】"
        )
    )
    prompt = _first_user_message(wired_agent)
    assert REAL_COLUMN_REQUIREMENT in prompt  # 真实列值
    assert style in prompt  # 真实项目风格
    assert "【--outline 复用值】" not in prompt  # outline 不再污染

    # 反向（可证伪）：不装配 → 两值皆不出现
    unwired, unwired_agent = _make_service()
    await unwired.run(_make_request(project_id=pid, chapter_id=created.id))
    unwired_prompt = _first_user_message(unwired_agent)
    assert REAL_COLUMN_REQUIREMENT not in unwired_prompt
    assert style not in unwired_prompt
