"""F44 T2 静态书级轨 · 章 brief 设定注入契约 — RED（#1185 盲区1 + A1/A3/A5/A10）。

权威来源：`.hermes/audit-writing-chain-20260915.md` P0-2 / P1-2 / P1-5 / P1-6。

本文件是 `test_book_service.py` 的兄弟文件：`test_book_service.py` 已 896 行
（`ci_cd/check_file_length.py` 限 900），故新增 describe 独立成文件，并**复用**
既有模块的 fixture / helper（`from ... import _plan, _outline, _make_deps`），
不复制一份（防两份漂移）。

契约（GREEN 必须满足）
---------------------
`BookService` 构造新增可选依赖，并在 `_build_chapter_brief` 中消费：

1. `context_builder: Callable[[uuid.UUID, Outline], Awaitable[str]] | None = None`
   —— 由装配层（`api/routers/books.py`）注入 F6/`ContextService` 的真实实现；
   产出文本进 brief 的【设定注入】段。None → 旧行为（占位符）。
2. brief 必须消费 `plan` 上已存在的真实数据（零 schema 改动，F15）：
   - `plan.character_ids` 非空 → 注入**真实角色摘要**，不得落「主角自定」占位符
   - 目标字数来自 `project_config_getter` 已注入的项目配置 `default_words`（F15）
3. `_build_chapter_brief` 签名扩展为
   `(plan, chapter, *, context: str = "", default_words: int | None = None)`。

RED 预期（当前 `book_service.py:866-876` 必须全部 FAIL）
-------------------------------------------------------
现状：
    character_summary = "主角自定" if not plan.character_ids else "见角色档案（plan.character_ids）"
    "【风格/偏好注入】遵循项目写作风格与用户偏好（偏好优先于通用文风）。"
即：角色恒占位符、writing_style 恒不读、伏笔恒缺席、字数恒缺席。

**盲区 1 处置**：`test_book_service.py:646-647` 的
`assert "偏好" in prompt or "风格" in prompt` 是恒真同源断言——它匹配的正是实现
里的硬编码字面量「【风格/偏好注入】」，实现改成空串仍 PASS。本文件改为断言
装配层注入的**真实可辨识值**，彻底掐断「断实现自己的字面量」这条路。

可证伪性：把对应注入改成空串 → 该用例必 FAIL。
"""

from __future__ import annotations

import logging
import pathlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.domain.models.context import (
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextSourceType,
)
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, WritingPlan
from inkflow.domain.services.book_service import BookService

# W2-C（#1183）：RED 期该符号尚不存在 → 延迟导入，避免 collection ERROR
# 连坐本文件既有的 15 条绿用例（TDD：新用例独立 FAIL，不阻断全文件）。
try:
    from inkflow.domain.services.chapter_brief import record_word_deviation
except ImportError:  # pragma: no cover - RED 期占位，GREEN 后必走不到
    # GREEN 后该分支不可达（符号恒存在）——保留占位仅为 RED 期不连坐全文件
    record_word_deviation = None  # type: ignore[assignment]  # 占位赋值与 import 类型不符

# ── fixture 锚点值（真实可辨识，与实现的硬编码字面量不同源）──────────

REAL_CONTEXT = "【角色】宁晚：太虚剑派掌门之女，医武不分家，替师出诊\n【伏笔】青铜药臼应显裂纹"
REAL_STYLE = "慢热日常·白描·忌打脸立威"
REAL_CHARACTER_NAME = "宁晚"
PLACEHOLDER_MAIN = "主角自定"
PLACEHOLDER_REF = "见角色档案"


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _outline(**overrides) -> Outline:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _make_deps(**overrides):
    """构造 BookService 全部 mock 依赖（镜像 test_book_service._make_deps）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    writer_factory = AsyncMock(return_value=fake_agent)

    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)

    deps = dict(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )
    deps.update(overrides)
    return deps


def _service(**overrides) -> BookService:
    return BookService(**_make_deps(**overrides))


def _brief(plan: WritingPlan, chapter: Outline, **kw) -> str:
    """调 `_build_chapter_brief` 取 brief 原文（纯函数）。"""
    return BookService._build_chapter_brief(plan, chapter, **kw)


# ── A1：真实角色/设定进 brief，占位符消除（#1175 / P0-2）──────────────


class TestSettingInjectionIntoBrief:
    def test_brief_carries_injected_context_text(self):
        """装配层注入的 F6 上下文文本原样进 brief（角色/伏笔/前文）。

        可证伪性：context 注入删掉（现状：该参数不存在）→ FAIL。
        """
        brief = _brief(_plan(character_ids=[uuid.uuid4()]), _outline(), context=REAL_CONTEXT)

        assert REAL_CHARACTER_NAME in brief
        assert REAL_CONTEXT in brief

    def test_context_service_output_actually_consumed_by_brief(self):
        """**盲区 5 · 消费面**：真实 `ContextService` 的产出一路进入 book brief。

        既有覆盖的盲区：`test_context_service.py`（567 行）全程 `MockSource`，
        只验证 `ContextService` 自己 assemble 出了什么——**零测试**验证该产出
        被写作链消费（`render_system_prompt` 的生产调用点仅 chat 轨 1 处）。

        本条驱动真实 `ContextService.render_system_prompt`，把其产出作为
        `context` 传入 brief，断言内容端到端抵达（assemble-only → 消费面）。
        """
        from inkflow.domain.services.context_service import ContextService

        # render_system_prompt 是纯函数（吃 ContextAssemblyResult）→ 直接驱动。
        # 契约要点是「ContextService 产出被 brief 消费」，故只构造最小合法的
        # ContextAssemblyResult（5 个必需字段齐备即可，不追求预算语义保真）。
        content = REAL_CHARACTER_NAME + "：太虚剑派掌门之女"
        result = ContextAssemblyResult(
            blocks=[
                ContextBlock(
                    item=ContextItem(
                        source=ContextSourceType.CHARACTER_SETTING,
                        title="角色",
                        content=content,
                    ),
                    layer=ContextLayer.COMPRESSIBLE,
                    token_count=len(content),
                    compressed=False,
                )
            ],
            budget_tokens=len(content),
            total_tokens=len(content),
            model="test-model",
            dropped=[],
        )
        rendered = ContextService.render_system_prompt(None, result)
        assert REAL_CHARACTER_NAME in rendered, "ContextService 渲染产物须含设定文本"

        brief = _brief(_plan(character_ids=[uuid.uuid4()]), _outline(), context=rendered)

        assert REAL_CHARACTER_NAME in brief, (
            "ContextService 产出必须被 book brief 消费（盲区 5 消费面）"
        )

    def test_brief_has_no_placeholder_when_character_ids_present(self):
        """plan.character_ids 非空 → brief 不含两种占位符串（#1175 占位符消除）。

        可证伪性：恢复现状实现 → FAIL（现状恒落「见角色档案（plan.character_ids）」）。
        """
        brief = _brief(_plan(character_ids=[uuid.uuid4()]), _outline(), context=REAL_CONTEXT)

        assert PLACEHOLDER_MAIN not in brief
        assert PLACEHOLDER_REF not in brief

    def test_brief_without_context_does_not_fake_character_summary(self):
        """无注入上下文且 character_ids 非空 → 不得谎报「见角色档案」占位符。

        占位符是「未接线」的伪装——必须显式缺席，不能冒充已注入。
        """
        brief = _brief(_plan(character_ids=[uuid.uuid4()]), _outline())

        assert PLACEHOLDER_REF not in brief
        assert PLACEHOLDER_MAIN not in brief


# ── A3：项目级 writing_style 实值进 brief（#1179 / P1-2）───────────────


class TestWritingStyleInjection:
    def test_brief_carries_project_writing_style_value(self):
        """brief 含项目级 writing_style **实值**，而非常量祈使句。

        可证伪性：style 注入删掉（现状恒为字面量）→ FAIL。
        """
        brief = _brief(_plan(), _outline(), project_style=REAL_STYLE)

        assert REAL_STYLE in brief

    def test_brief_style_is_value_not_literal_imperative(self):
        """风格段必须携带实值：只有常量祈使句而无 REAL_STYLE → FAIL。

        这条**替代** `test_book_service.py:646-647` 的恒真同源断言
        （`assert "偏好" in prompt or "风格" in prompt` 匹配的正是实现里的
        硬编码「【风格/偏好注入】」，把实现改成空串仍 PASS）。
        此处断言 fixture 的真实串——实现改成空串/删注入 → 必 FAIL。
        """
        brief = _brief(_plan(), _outline(), project_style=REAL_STYLE)

        assert REAL_STYLE in brief, "风格段必须含项目 writing_style 实值，不能只有常量祈使句"


# ── A10：字数约束进 brief（#1183 / P1-6）───────────────────────────────


class TestWordTargetInjection:
    def test_brief_carries_target_word_count(self):
        """brief 含目标字数（来自 project.config.default_words，F15 字段已存在）。

        可证伪性：字数注入删掉（现状 book 三轨均无字数）→ FAIL。
        """
        brief = _brief(_plan(), _outline(), default_words=800000)

        assert "800000" in brief or "800,000" in brief


def _fake_agent():
    """最小 agent stub（镜像 test_book_service._make_deps 的 fake_agent 形态）。"""
    from types import SimpleNamespace

    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    return agent


# ── 盲区 1（#1185）：修正既有文件里的**恒真同源断言** ──────────────────
#
# 背景：`test_book_service.py:646-647` 原断言为
#     assert "时间旅途中发现悖论" in prompt
#     assert "偏好" in prompt or "风格" in prompt     # ← 与实现同源
# 后者匹配的正是 `book_service.py:875` 的硬编码字面量「【风格/偏好注入】…偏好…」——
# 把角色摘要改成空串、把风格注入删成空，它照样 PASS，缺陷因此存活至今。
#
# 归属说明：该用例体源自 test_book_service.py，因**基文件 896 行贴 900 护栏**
# （安全余量仅 4 行，任何追加必触线）故整体迁入本兄弟文件，基文件保持 HEAD 原状。
# 契约等价性：此处用例的**唯一增量**是把恒真断言换成真实注入数据断言，
# 并用本用例私有的 deps 注入（不改共享 fixture，避免其余用例构造期炸）。


@pytest.mark.asyncio
async def test_delegate_chapter_brief_carries_real_injected_data():
    """章 brief（大纲切片 + F6 注入）→ writer_factory system_prompt（§5.1）。

    **盲区 1 修正版**：断言真实注入数据（角色名/伏笔/风格值），
    禁止断言实现里的硬编码字面量。

    可证伪性（段 4.3 自证）：把 brief 的 character_summary 改成空串
    → 本用例 FAIL（已实测：基线 7 failed → 改坏后 6 failed 1 passed）。
    """
    repo = AsyncMock()
    plan = _plan()
    chapter = _outline(description="主角在时间旅途中发现悖论")
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)

    deps = dict(
        repo=repo,
        writer_factory=AsyncMock(return_value=_fake_agent()),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        # 真实注入源：仅本用例注入，不动共享 fixture
        context_builder=AsyncMock(return_value=REAL_CONTEXT),
        project_config_getter=AsyncMock(return_value={"writing_style": REAL_STYLE}),
    )
    svc = BookService(**deps)

    execution_id = await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    assert execution_id
    deps["writer_factory"].assert_awaited_once()
    prompt = deps["writer_factory"].await_args.kwargs.get("system_prompt", "")

    # 大纲切片
    assert "时间旅途中发现悖论" in prompt
    # 真实注入数据（非硬编码字面量）
    assert REAL_CHARACTER_NAME in prompt, "写作 prompt 须含真实角色名"
    assert "青铜药臼应显裂纹" in prompt, "写作 prompt 须含注入的伏笔"
    assert REAL_STYLE in prompt, "写作 prompt 须含项目 writing_style 真实值"
    # 占位符必须消失
    assert PLACEHOLDER_MAIN not in prompt
    assert PLACEHOLDER_REF not in prompt


# ── 元测试：钉住基文件现有的恒真断言（#1185 遗留台账）──────────────────


def test_base_file_still_has_known_tautological_assertion():
    """基文件 `test_book_service.py` 仍含已知的**恒真同源断言**（#1185 盲区 1）。

    该断言匹配的是实现 `book_service.py:875` 里的硬编码字面量，因此
    「把角色摘要改成空串」不会让它 FAIL —— 这正是缺陷存活至今的原因。

    ⚠️ 本测试的**目的不是认可它**，而是把「它还在」这一事实钉在测试里：
    - 若有人修正/删除了基文件那条断言 → 本测试 FAIL → 提醒同步删除
      本文件的重复用例 `test_delegate_chapter_brief_carries_real_injected_data`
      （届时可把它搬回基文件原位，护栏压力消失）。
    - 台账：issue #1185；基文件护栏线 900，基线 896，安全余量 4 行。
    """
    base = pathlib.Path(__file__).with_name("test_book_service.py")
    text = base.read_text(encoding="utf-8")

    tautology = 'assert "偏好" in prompt or "风格" in prompt'
    assert tautology in text, (
        "基文件的恒真断言已被修改/删除 —— 请把本文件的 "
        "test_delegate_chapter_brief_carries_real_injected_data 迁回基文件原位，"
        "并删除本元测试（#1185）"
    )

    # 同时钉住护栏余量事实：基文件行数若降到有空间（<= 890），说明可以搬回去
    n_lines = len(text.splitlines())
    assert n_lines > 890, (
        f"基文件已降至 {n_lines} 行（<=890，护栏有空间）—— "
        "请把有效断言迁回基文件原位并清理本文件重复用例（#1185）"
    )


# ── W2-C（#1183）：user 消息字数 + 生成后偏差记录 ──────────────────────
#
# 背景：W1 已交付 brief 【目标字数】段（TestWordTargetInjection 全绿）。
# 但 issue #1183 正文列明的另两条验收未闭：
#   F2  user 消息无字数（三轨均 f"请撰写章节《{name}》：{description}"）
#   ④   生成后无 count_words 偏差记录（「不建议硬失败」= 记录而非阻断）
# 本批（W2-C）只补这两条，不动已绿的 brief 注入。

TARGET_WORDS = 800000


async def _invoke_capture(plan: WritingPlan, chapter: Outline, **svc_over):
    """驱动 T2 `_delegate_chapter`，返回 writer_factory 收到的 messages。"""
    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)
    deps = dict(
        repo=AsyncMock(),
        writer_factory=AsyncMock(return_value=agent),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        project_config_getter=AsyncMock(return_value={"default_words": TARGET_WORDS}),
    )
    deps.update(svc_over)
    svc = BookService(**deps)
    await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)
    return agent.invoke.await_args.args[0]


@pytest.mark.asyncio
async def test_user_message_carries_target_word_count():
    """user 消息须携带目标字数（F2：三轨 user 消息均无字数）。

    可证伪性：删掉 user 消息里的字数后缀 → FAIL
    （现状 `book_service.py:844` 恒为 `请撰写章节《{name}》：{description}`）。
    """
    messages = await _invoke_capture(_plan(), _outline())

    user = next(m for m in messages if m["role"] == "user")["content"]
    assert str(TARGET_WORDS) in user, "user 消息须含目标字数"
    assert "请撰写章节" in user, "原有指令语义不得丢失"


# ── G2：生成后字数偏差记录（记录，不硬失败）──────────────────────────


def test_word_deviation_is_recorded_within_tolerance(caplog):
    """产出字数落在目标 ±30% 内 → 记录偏差，不告警。

    issue 验收：「连续多章产出的 word_count 落在预期区间（容忍 LLM 漂移，
    如 ±30%）」「不建议硬失败」。可证伪性：删掉偏差记录 → FAIL（无日志）。
    """
    with caplog.at_level(logging.INFO):
        deviation = record_word_deviation("字" * TARGET_WORDS, TARGET_WORDS, chapter_name="第一章")

    assert deviation == pytest.approx(1.0, abs=0.01)
    assert any("字数" in r.message or "word" in r.message.lower() for r in caplog.records)


def test_word_deviation_flags_drift_beyond_tolerance(caplog):
    """产出字数超出 ±30% → 记录**告警**（仍不抛异常，不阻断写作链）。

    可证伪性：把告警降级为 info / 去掉阈值判断 → FAIL。
    """
    with caplog.at_level(logging.WARNING):
        deviation = record_word_deviation(
            "字" * (TARGET_WORDS // 3), TARGET_WORDS, chapter_name="第一章"
        )

    assert deviation < 0.7
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_word_deviation_without_target_does_not_record(caplog):
    """无目标字数（未配置）→ 不记录、不告警（回归：不得凭空告警）。"""
    with caplog.at_level(logging.DEBUG):
        deviation = record_word_deviation("正文", None, chapter_name="第一章")

    assert deviation is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ── A11′：章级写作要求**同源**断言（#1200 补强）────────────────────────
#
# 与 A4 的差别：A4 用**手工构造** `extra={"writing_requirements": ...}` 驱动，
# 断言的是 `outline.extra` 通道 —— 而真实写入位置是 `chapters.writing_requirements`
# **表列**（GUI 章级栏 → PATCH /api/v1/chapters/{id}）。两者不同源：
# 把真实数据通道断掉，A4 照样 PASS（同源假绿，W2-E 报告已证）。
#
# 本组用**真实 repo 造列值**驱动装配点，改坏装配（getter 传 None）必 FAIL。

REAL_COLUMN_REQUIREMENT = "本章需写主角第一次独立出诊（GUI 章级栏写入）"

#: InkFlow 主键惯例：DB int64 ↔ uuid.UUID(int=...)。**禁用 uuid4()** ——
#: uuid4().int 溢出 SQLite INTEGER（ai-traps 已知族），故用递增小整数造 id。
_ID_SEQ = iter(range(10_000, 20_000))


def _db_uid() -> uuid.UUID:
    """递增小整数 UUID（可安全往返 SQLite INTEGER 主键）。"""
    return uuid.UUID(int=next(_ID_SEQ))


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（启用 FK）——镜像既有同层 fixture 形态。"""
    import inkflow.infrastructure.database.models  # noqa: F401  # 注册全部 ORM
    from inkflow.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_chapter_column(session_factory, project_id: uuid.UUID, value: str):
    """真实落一行 chapters（writing_requirements 列 = value）；返回落库实体。"""
    from inkflow.domain.models.chapter import Chapter
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )

    repo = SQLiteChapterRepository(session_factory)
    return await repo.add_chapter(
        Chapter(id=_db_uid(), project_id=project_id, title="第一章", writing_requirements=value)
    )


async def test_chapter_column_value_reaches_brief_via_assembly(db_session):
    """#1200 同源断言：`chapters` 列表值经装配层 → 章 dict → brief（真实 repo 造数据）.

    可证伪性：`BookService(chapter_requirements_getter=None)` → getter 未装配
    → 列值取不到 → `REAL_COLUMN_REQUIREMENT not in brief` → 必 FAIL。
    """
    from inkflow.infrastructure.database.models.project import ProjectORM
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )

    pid = _db_uid()
    db_session.add(ProjectORM(id=pid.int, name="项目"))
    await db_session.commit()

    created = await _seed_chapter_column(db_session, pid, REAL_COLUMN_REQUIREMENT)

    repo = SQLiteChapterRepository(db_session)

    async def _getter(cid: uuid.UUID) -> str | None:
        chapter = await repo.get_chapter(cid)
        value = getattr(chapter, "writing_requirements", None) if chapter else None
        return value if isinstance(value, str) and value else None

    outline = _outline(project_id=pid, chapter_id=created.id)

    # 正向：装配 getter → 列值进章 dict → 进 brief
    wired = _service(chapter_requirements_getter=_getter)
    chapter_dict = (await wired._to_chapter_dicts([outline]))[0]
    assert chapter_dict["writing_requirements"] == REAL_COLUMN_REQUIREMENT
    assert REAL_COLUMN_REQUIREMENT in _brief(_plan(project_id=pid), chapter_dict)

    # 反向（可证伪）：不装配 getter → 列值取不到（证明上一条断言来自真实列）
    unwired = _service(chapter_requirements_getter=None)
    chapter_dict_none = (await unwired._to_chapter_dicts([outline]))[0]
    assert chapter_dict_none["writing_requirements"] is None
    assert REAL_COLUMN_REQUIREMENT not in _brief(_plan(project_id=pid), chapter_dict_none)


async def test_chapter_column_absent_falls_back_to_outline_extra(db_session):
    """回退语义：章无关联 / 列值为空 → 不破 `outline.extra` 既有通道（W1 断言不回归）。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    pid = _db_uid()
    db_session.add(ProjectORM(id=pid.int, name="项目"))
    await db_session.commit()

    async def _empty_getter(cid: uuid.UUID) -> str | None:
        return None

    service = _service(chapter_requirements_getter=_empty_getter)

    # 列值为空 → 回退 extra
    outline = _outline(project_id=pid, extra={"writing_requirements": "来自 extra 通道"})
    chapter_dict = (await service._to_chapter_dicts([outline]))[0]
    assert chapter_dict["writing_requirements"] == "来自 extra 通道"

    # chapter_id 为 None → 不走 getter，直接回退（降级不抛错）
    orphan = _outline(project_id=pid, chapter_id=None, extra={"writing_requirements": "孤儿章"})
    orphan_dict = (await service._to_chapter_dicts([orphan]))[0]
    assert orphan_dict["writing_requirements"] == "孤儿章"
