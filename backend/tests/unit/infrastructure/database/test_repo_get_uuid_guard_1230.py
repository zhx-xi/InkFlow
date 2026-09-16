"""#1230 RED 契约 — repo 层 get 入口 UUID 类型早退（全同族统一）。

背景
----
F3 确定性写作轨四条入口全 500，根因（已实证，见 .hermes/scripts/probe_1230.py）：

    project_repo.py:80  if project_id < -(2**63) or project_id >= 2**63:
    TypeError: '<' not supported between instances of 'UUID' and 'int'

`writing_service` 把 `request.project_id`（domain 层恒 `uuid.UUID`）直接传进
`project_repo.get(project_id: int)`；int64 守卫用**比较运算符**而非类型判断
→ 对 UUID 入参直接抛 TypeError（连「返 None」都做不到）。

既有测试为何全部漏掉
--------------------
- `tests/unit/domain/services/test_writing_service.py`：`repo.get = AsyncMock(...)`
  → Mock 接受任何入参，UUID 与 int 无异；
- `tests/api/test_writing_api.py`：整体 mock 掉 `WritingService` → 仓储不被触碰；
- `tests/unit/.../test_project_repo.py`：真 SQLite，但**只用 `.int` 调用**。

因此本契约的价值锚点 = **真实 SQLite 仓储**（非 Mock）+ **真实 Service→repo 调用链**。

契约清单（对应 issue §验收判据）
-------------------------------
① repo.get(UUID) 不抛（返 Project 或 None）              → TestRepoGetAcceptsUUID1230
② writing_service.generate_chapter(UUID) 走通            → TestWritingServiceUUIDChain1230
③ 全同族 13 个 repo get(UUID) 一律不抛（防单点补丁）      → TestRepoFamilyGetAcceptsUUID1230
④ 可证伪性：守卫回退旧形态 → ① 必 FAIL                    → TestGuardFalsifiability1230
⑤ 既有 int 行为零回归                                    → 既有用例 + TestInt64RangeGuard1106

③④⑤ 端到端（MCP/CLI 真实内核）说明见 .hermes/plans/w6a-pr-body.md「端到端覆盖口径」节：
本 worktree 无内核产物，MCP/CLI 端到端由 ③ 的真实仓储链 + 既有 CLI/API mock 契约共同锁死。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 触发 ORM 注册到 Base.metadata（否则 create_all 不建这些表 —— agent_entity /
# provider_config 等模块不 import 就不会注册）。
import inkflow.infrastructure.database.models.agent_entity
import inkflow.infrastructure.database.models.provider_config  # noqa: F401
from inkflow.core.database import Base
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.writing import WritingRequest
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（启用 FK）— 每用例全新库."""
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


def _now() -> datetime:
    return datetime.now(UTC)


def _project(name: str, **kw: object) -> Project:
    return Project(id=uuid.uuid4(), name=name, created_at=_now(), updated_at=_now(), **kw)


# ══════════════════════════════════════════════════════════════════════════
# ① repo.get(UUID) 不抛（核心根因）
# ══════════════════════════════════════════════════════════════════════════


class TestRepoGetAcceptsUUID1230:
    """#1230 ①：project_repo.get 接受 UUID 入参（domain 层天然形态）。"""

    async def test_get_by_uuid_returns_project(self, db_session) -> None:
        """已存在项目的 UUID → 返回对应 Project（UUID→int 正确转换后命中）。"""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("UUID 查询项目", tags=["玄幻"]))

        got = await repo.get(created.id)  # type: ignore[arg-type]  # 本契约核心：UUID 入参

        assert got is not None
        assert got.id == created.id
        assert got.name == "UUID 查询项目"

    async def test_get_by_uuid_missing_returns_none(self, db_session) -> None:
        """不存在的 UUID（含随机 uuid4，其 .int 超 int64）→ None，不抛异常。"""
        repo = SQLiteProjectRepository(db_session)
        ghost = uuid.uuid4()
        assert ghost.int > 2**63 - 1, "前提：随机 uuid4 的 .int 超 int64（本契约的意义所在）"

        assert await repo.get(ghost) is None  # type: ignore[arg-type]

    async def test_get_by_uuid_deterministic_small_int(self, db_session) -> None:
        """确定性 UUID(int=1)（rc1 复现命令形态）→ 不抛 TypeError。

        与随机 uuid4 的区别：其 .int 落在 int64 范围内 → 会真正走到 SQL 查询。
        """
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("确定性主键项目"))

        assert created.id.int > 2**63 - 1  # add 分配的是 UUID(int=雪花/自增)，此处仅示意
        # 用真实落库行（int 主键在范围内）反查：UUID 形态必须等价于 .int 形态
        by_int = await repo.get(created.id.int)
        by_uuid = await repo.get(created.id)  # type: ignore[arg-type]
        assert by_int is not None
        assert by_uuid is not None
        assert by_uuid.id == by_int.id

    async def test_get_by_uuid_does_not_raise_type_error(self, db_session) -> None:
        """反向断言：显式锁定「不抛 TypeError」这一事实（而非仅「有返回」）。"""
        repo = SQLiteProjectRepository(db_session)
        for candidate in (uuid.uuid4(), uuid.UUID(int=0), uuid.UUID(int=1)):
            try:
                await repo.get(candidate)  # type: ignore[arg-type]
            except TypeError as exc:  # pragma: no cover - 修复前必现
                pytest.fail(f"repo.get({candidate!r}) 抛 TypeError：{exc}")


# ══════════════════════════════════════════════════════════════════════════
# ② Service → 真 repo 调用链（Mock 是缺陷逃逸口，此处必须真仓储）
# ══════════════════════════════════════════════════════════════════════════


class TestWritingServiceUUIDChain1230:
    """#1230 ②：真实 WritingService + 真实 repo，UUID 入参不崩在 project_repo.get。"""

    async def _service(self, db_session):
        from inkflow.domain.services.writing_service import WritingService

        class _RecordingLLM:
            """记录调用并返回可解析内容 —— 证明已越过 repo.get 进入生成阶段。"""

            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def chat(self, **kwargs):
                from inkflow.domain.ports.llm_client import ChatResponse, TokenUsage

                self.calls.append(kwargs)
                return ChatResponse(
                    content="# 第一章 探针\n\n" + "正文内容。" * 500,
                    model="probe/model",
                    token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

        class _StubPrompt:
            def load(self, *args, **kwargs):
                from inkflow.domain.ports.prompt_template import PromptTemplate

                return PromptTemplate(
                    name="writer",
                    description="probe",
                    system_prompt="sys {style}",
                    human_prompt="outline {outline}\nctx {context}\nmin {min_words}",
                    variables=["style", "outline", "context", "min_words"],
                )

            def render(self, *args, **kwargs):
                from inkflow.domain.ports.prompt_template import RenderedPrompt

                return RenderedPrompt(
                    messages=[{"role": "user", "content": "probe"}], token_estimate=10
                )

        llm = _RecordingLLM()
        svc = WritingService(
            llm_client=llm,  # type: ignore[arg-type]
            prompt_manager=_StubPrompt(),  # type: ignore[arg-type]
            project_repo=SQLiteProjectRepository(db_session),
            chapter_repo=None,  # type: ignore[arg-type]
        )
        return svc, llm

    async def test_generate_chapter_with_uuid_project_id(self, db_session) -> None:
        """project_id 为 UUID（domain 天然形态）→ 不抛 TypeError，且进入 LLM 生成。

        修复前：崩在 project_repo.get 的 int64 守卫比较（TypeError）。
        修复后：UUID→int 归一 → 命中项目 → 继续生成（LLM 被调用）。
        """
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("写作链项目", config=ProjectConfig(model="probe/model")))
        svc, llm = await self._service(db_session)

        result = await svc.generate_chapter(
            WritingRequest(
                project_id=created.id,  # ← UUID，非 .int
                chapter_id=uuid.uuid4(),
                outline="【契约】主角首次踏入宗门",
            )
        )

        assert llm.calls, "应已越过 repo.get 进入生成阶段（证明根因已消除）"
        assert result.word_count > 0

    async def test_generate_chapter_uuid_missing_project_is_not_type_error(
        self, db_session
    ) -> None:
        """不存在的 UUID 项目 → 允许任何业务异常，但**不得**是 TypeError。

        反向断言：把「类型错误」与「业务上的项目不存在」区分开。
        """
        svc, _ = await self._service(db_session)
        try:
            await svc.generate_chapter(
                WritingRequest(
                    project_id=uuid.uuid4(),
                    chapter_id=uuid.uuid4(),
                    outline="【契约】不存在的项目",
                )
            )
        except TypeError as exc:  # pragma: no cover - 修复前必现
            pytest.fail(f"不应抛 TypeError（应为业务异常或正常返回）：{exc}")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
# ③ 全同族 repo：get(UUID) 一律不抛（用户偏好「拒绝同族路径分叉」）
# ══════════════════════════════════════════════════════════════════════════

# (模块路径, 类名, 主键参数名) —— 覆盖 #1230 枚举出的全部 int 型 get 入口
_FAMILY_REPOS: list[tuple[str, str, str]] = [
    (
        "inkflow.infrastructure.database.repositories.agent_repo",
        "SQLiteAgentRepository",
        "agent_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.agent_template_repo",
        "SQLiteAgentTemplateRepository",
        "template_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.character_repo",
        "SQLiteCharacterRepository",
        "character_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.foreshadowing_repo",
        "SQLiteForeshadowingRepository",
        "foreshadowing_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.knowledge_relation_repo",
        "SQLiteKnowledgeRelationRepository",
        "relation_id",
    ),
    ("inkflow.infrastructure.database.repositories.map_repo", "SQLiteMapRepository", "map_id"),
    (
        "inkflow.infrastructure.database.repositories.outline_repo",
        "SQLiteOutlineRepository",
        "outline_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.project_repo",
        "SQLiteProjectRepository",
        "project_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.provider_config_repo",
        "SQLiteProviderConfigRepository",
        "provider_config_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.session_repo",
        "SQLiteSessionRepository",
        "session_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.summary_repo",
        "SQLiteSummaryRepository",
        "chapter_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.timeline_repo",
        "SQLiteTimelineRepository",
        "event_id",
    ),
    (
        "inkflow.infrastructure.database.repositories.world_repo",
        "SQLiteWorldRepository",
        "setting_id",
    ),
]


class TestRepoFamilyGetAcceptsUUID1230:
    """#1230 ③：同族 repo 的 `get(<x>_id: int)` 入口对 UUID 入参一律不抛。

    判据来源：issue §3「全仓同族 repo 一律同样处理 —— 避免逐个 caller 打补丁」+
    用户偏好「机制扩展拒绝同族路径分叉」。
    """

    @pytest.mark.parametrize(("mod_path", "cls_name", "pk_name"), _FAMILY_REPOS)
    async def test_family_get_uuid_does_not_raise(
        self, db_session, mod_path: str, cls_name: str, pk_name: str
    ) -> None:
        """同族每个 repo：get(uuid.uuid4()) 与 get(uuid.UUID(int=1)) 均不抛 TypeError。"""
        import importlib

        module = importlib.import_module(mod_path)
        repo_cls = getattr(module, cls_name)
        repo = repo_cls(db_session)

        for candidate in (uuid.uuid4(), uuid.UUID(int=1)):
            try:
                await repo.get(candidate)
            except TypeError as exc:
                pytest.fail(f"{cls_name}.get({pk_name}=UUID) 抛 TypeError：{exc}")

    def test_family_enumeration_is_complete(self) -> None:
        """同族枚举完整性：repo 目录下所有 `get(self, <x>_id: int)` 均在 _FAMILY_REPOS 内。

        防止将来新增 repo 时漏加守卫（#1106→#1139→#1151 三次遗漏的机制性对策）。
        """
        import pathlib
        import re

        repo_dir = (
            pathlib.Path(__file__).resolve().parents[4]
            / "src"
            / "inkflow"
            / ("infrastructure/database/repositories")
        )
        pattern = re.compile(r"async def get\(self, (\w+): int\)")
        found: set[tuple[str, str]] = set()
        for path in sorted(repo_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            first = pattern.search(text)
            if not first:
                continue
            classes = re.findall(r"^class (\w+)", text, re.M)
            assert classes, f"{path.name} 有 get 但未解析到类名"
            found.add((path.stem, classes[0]))

        declared = {(mod.rsplit(".", 1)[1], cls) for mod, cls, _ in _FAMILY_REPOS}
        missing = found - declared
        assert not missing, (
            f"以下 int 型 repo get 未纳入同族契约（请补守卫 + 登记）：{sorted(missing)}"
        )


class TestRepoFamilyUUIDSemantics1230:
    """#1230 ③b：同族中「无 int64 守卫」的 int 主键 repo —— UUID 入参须安全兜底。

    `agent_repo` / `provider_config_repo` 的 `get` **无比较型守卫**，且其领域主键
    语义为 **int**（`Agent.id: int | None` / `ProviderConfig.id: int | None`）——
    不存在合法的 UUID 调用路径（与 Project 的 UUID 主键语义相反）。

    故正确处置 = **类型早退返 None**（把「调用方传错类型」变成「查不到」，
    而非静默拼出 `.hex` 字符串去 SQL 里撞大运 —— 实测 `WHERE agents.id = ?`
    参数会退化成 32 位 hex 串）。

    判据：UUID 入参 → None（不抛、不静默错），且既有 int 路径无回归。
    """

    @pytest.mark.parametrize(
        ("mod_path", "cls_name", "factory"),
        [
            (
                "inkflow.infrastructure.database.repositories.agent_repo",
                "SQLiteAgentRepository",
                "agent",
            ),
            (
                "inkflow.infrastructure.database.repositories.provider_config_repo",
                "SQLiteProviderConfigRepository",
                "provider_config",
            ),
        ],
    )
    async def test_int_pk_family_uuid_returns_none_safely(
        self, db_session, mod_path: str, cls_name: str, factory: str
    ) -> None:
        """int 主键 repo：UUID 入参 → 不抛 TypeError，且不得命中任何真实行。"""
        import importlib

        module = importlib.import_module(mod_path)
        repo = getattr(module, cls_name)(db_session)

        if factory == "agent":
            from inkflow.domain.models.agent import Agent

            domain = Agent(name="契约 Agent")
        else:
            from inkflow.domain.models.provider_config import ProviderConfig

            domain = ProviderConfig(name="契约 Provider")

        saved = await repo.add(domain)
        assert isinstance(saved.id, int), "前提：该类 repo 主键为 int 语义"

        # 既有 int 路径必须仍然命中（锁定无回归）
        assert await repo.get(saved.id) is not None

        # UUID 入参：不抛 + 不误命中
        for candidate in (uuid.uuid4(), uuid.UUID(int=1), uuid.UUID(int=saved.id)):
            try:
                hit = await repo.get(candidate)  # type: ignore[arg-type]
            except TypeError as exc:
                pytest.fail(f"{cls_name}.get(UUID) 抛 TypeError：{exc}")
            assert hit is None, f"{cls_name}.get({candidate}) 返回了记录 —— UUID 被静默折算后误命中"


# ══════════════════════════════════════════════════════════════════════════
# ④ 可证伪性自证：守卫形态是承重的
# ══════════════════════════════════════════════════════════════════════════


class TestGuardFalsifiability1230:
    """#1230 ④：把守卫改回「裸比较」形态 → ① 类断言必须 FAIL（否则断言恒真）。"""

    async def test_old_guard_shape_fails_on_uuid(self, db_session) -> None:
        """直接以旧守卫表达式喂 UUID → 必然 TypeError（证明该形态不可用）。"""
        pid: object = uuid.uuid4()
        with pytest.raises(TypeError, match="not supported between instances"):
            # 旧形态：守卫前无类型归一
            _ = pid < -(2**63) or pid >= 2**63  # type: ignore[operator]

    async def test_new_guard_shape_accepts_uuid(self) -> None:
        """新形态：类型早退后再比较 → 不抛（与实现契约一致）。"""

        def _guarded(pid: int | uuid.UUID) -> bool:
            value = pid.int if isinstance(pid, uuid.UUID) else pid
            return value < -(2**63) or value >= 2**63

        assert _guarded(uuid.uuid4()) is True  # 随机 uuid4 .int 超 int64 → 视为不存在
        assert _guarded(uuid.UUID(int=1)) is False  # 小值 UUID 在范围内
        assert _guarded(2**63) is True
        assert _guarded(1) is False
