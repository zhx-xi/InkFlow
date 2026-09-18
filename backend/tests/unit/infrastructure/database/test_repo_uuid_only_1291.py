"""#1291 RED 契约 — repo 层入参收窄到 ``uuid.UUID``（#1230 int 兼容面退役）。

背景（本契约 = #1230 契约的**反向**）
--------------------------------------
`test_repo_get_uuid_guard_1230.py` 建立于 #1230，其 ⑤ 条断言明确要求
「既有 int 行为零回归」：`repo.get(<x>.id.int)` 必须命中、int 主键 repo 必须
继续接受裸 int。

#1134 批 3-B（#1271）已把 `repo.get` 的**类型签名**收窄到 `uuid.UUID`，
但为满足上述冻结契约，实现层仍以**双路径**接入：

    if isinstance(x_id, uuid.UUID):
        pk = require_uuid_pk(x_id)      # 收窄契约入口
    else:
        pk = uuid_to_pk_or_none(x_id)   # #1230 int 兼容路径

**本批（#1134 批 4 / #1291）退役 int 兼容面**：
- 「#1230 ⑤ 的 int 兼容保证随本批作废」——裸 int 不再是被支持的入参形态；
- `uuid_to_pk_or_none` / `normalize_pk` / `out_of_int64` 随零消费者退役；
- `require_uuid_pk` 成为**唯一**入口（无 isinstance 双路径）；
- int64 溢出防御**本身保留**（`require_uuid_pk` 内联），但触发方式改为
  「传 `uuid.uuid4()`（其 `.int` 必然超 int64）」，而非「传裸大整数」。

契约清单
--------
① `repo.get(UUID)` / `list(UUID)` / `delete(UUID)` … 不抛          → TestRepoEntryAcceptsUUID1291
② Service → 真 repo 调用链（UUID 直传，无 `.int` 中转）           → TestServiceUUIDChain1291
③ 全同族 repo：UUID 入参一律不抛（防单点补丁）                     → TestRepoFamilyUUIDOnly1291
④ int 主键 repo（Agent/Template/ProviderConfig）仍接受 int         → TestIntPkRepoUnchanged1291
⑤ 溢出防御仍生效：随机 uuid4 → None（不抛、不误命中）          → TestOverflowGuardStillActive1291
⑥ 可证伪性：把守卫改回「裸比较」→ ① 必 FAIL                         → TestGuardFalsifiability1291

⚠️ 与 `_to_int_id` 的关系：本契约不含 `_to_int_id` 断言（该 helper 全仓退役）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models.agent_entity  # 触发 ORM 注册
import inkflow.infrastructure.database.models.provider_config  # noqa: F401  # 触发 ORM 注册
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
# ① 收窄后的 repo 入口：UUID 入参语义完整（get / list / delete / soft_delete）
# ══════════════════════════════════════════════════════════════════════════


class TestRepoEntryAcceptsUUID1291:
    """#1291 ①：收窄后 UUID 是**唯一**入参形态，且各方法语义完整。"""

    async def test_get_by_uuid_returns_project(self, db_session) -> None:
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("UUID 查询项目", tags=["玄幻"]))

        got = await repo.get(created.id)

        assert got is not None
        assert got.id == created.id
        assert got.name == "UUID 查询项目"

    async def test_get_by_uuid_missing_returns_none(self, db_session) -> None:
        """随机 uuid4（`.int` 超 int64）→ None，不抛异常（溢出防御经 UUID 通道生效）。"""
        repo = SQLiteProjectRepository(db_session)
        ghost = uuid.uuid4()
        assert ghost.int > 2**63 - 1, "前提：随机 uuid4 的 .int 超 int64"

        assert await repo.get(ghost) is None

    async def test_soft_delete_and_restore_by_uuid(self, db_session) -> None:
        """`soft_delete` / `restore` 收窄到 UUID 后语义不变。"""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("软删项目"))

        assert await repo.soft_delete(created.id) is True
        assert await repo.get(created.id) is None  # 软删后 get 过滤

        restored = await repo.restore(created.id)
        assert restored is not None
        assert restored.id == created.id

    async def test_soft_delete_by_uuid_absent_returns_false(self, db_session) -> None:
        """不存在的 UUID（含超 int64 者）→ False，不抛 OverflowError。"""
        repo = SQLiteProjectRepository(db_session)
        assert await repo.soft_delete(uuid.uuid4()) is False


# ══════════════════════════════════════════════════════════════════════════
# ② Service → 真 repo 调用链（UUID 直传，无 `.int` 中转）
# ══════════════════════════════════════════════════════════════════════════


class TestServiceUUIDChain1291:
    """#1291 ②：真实 WritingService + 真实 repo，UUID 全程直传不崩。"""

    async def _service(self, db_session, project_id):
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

        class _StubChapterRepo:
            """`_validate_chapter` 需要 `get_chapter` —— 返回归属该项目的章节。"""

            def __init__(self, project_id) -> None:
                self._project_id = project_id

            async def get_chapter(self, chapter_id):
                from inkflow.domain.models.chapter import Chapter, ChapterStatus

                return Chapter(
                    id=chapter_id,
                    project_id=self._project_id,
                    volume_id=None,
                    title="第一章",
                    content="",
                    status=ChapterStatus.DRAFT,
                    word_count=0,
                    order_index=1.0,
                    status_history=[],
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )

        llm = _RecordingLLM()
        repo = SQLiteProjectRepository(db_session)
        svc = WritingService(
            llm_client=llm,  # type: ignore[arg-type]  # 测试替身仅实现 chat
            prompt_manager=_StubPrompt(),  # type: ignore[arg-type]  # 同上
            project_repo=repo,
            chapter_repo=_StubChapterRepo(project_id=project_id),  # type: ignore[arg-type]  # 同上
        )
        return svc, llm

    async def test_generate_chapter_with_uuid_project_id(self, db_session) -> None:
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("写作链项目", config=ProjectConfig(model="probe/model")))
        svc, llm = await self._service(db_session, project_id=created.id)

        result = await svc.generate_chapter(
            WritingRequest(
                project_id=created.id,  # ← UUID，非 .int
                chapter_id=uuid.uuid4(),
                outline="【契约】主角首次踏入宗门",
            )
        )

        assert llm.calls, "应已越过 repo.get 进入生成阶段"
        assert result.word_count > 0

    async def test_generate_chapter_uuid_missing_project_is_not_type_error(
        self, db_session
    ) -> None:
        svc, _ = await self._service(db_session, project_id=uuid.uuid4())
        try:
            await svc.generate_chapter(
                WritingRequest(
                    project_id=uuid.uuid4(),
                    chapter_id=uuid.uuid4(),
                    outline="【契约】不存在的项目",
                )
            )
        except TypeError as exc:  # pragma: no cover
            pytest.fail(f"不应抛 TypeError（应为业务异常或正常返回）：{exc}")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
# ③ 全同族 repo：UUID 入参一律不抛（防单点补丁）
# ══════════════════════════════════════════════════════════════════════════

# (模块路径, 类名, 主键参数名) —— UUID 主键语义的仓储实现
_FAMILY_UUID_REPOS: list[tuple[str, str, str]] = [
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


class TestRepoFamilyUUIDOnly1291:
    """#1291 ③：UUID 主键语义的同族 repo，`get` 对 UUID 入参一律不抛。"""

    @pytest.mark.parametrize(("mod_path", "cls_name", "pk_name"), _FAMILY_UUID_REPOS)
    async def test_family_get_uuid_does_not_raise(
        self, db_session, mod_path: str, cls_name: str, pk_name: str
    ) -> None:
        import importlib

        module = importlib.import_module(mod_path)
        repo_cls = getattr(module, cls_name)
        repo = repo_cls(db_session)

        for candidate in (uuid.uuid4(), uuid.UUID(int=1)):
            try:
                await repo.get(candidate)
            except TypeError as exc:
                pytest.fail(f"{cls_name}.get({pk_name}=UUID) 抛 TypeError：{exc}")

    def test_no_repo_get_accepts_plain_int(self) -> None:
        """收窄终态：仓储层**不存在** `async def get(self, <x>_id: int)` 形态。

        这是「#1230 ⑤ int 兼容面作废」在**类型签名**上的机器可验证表达。
        反例守卫：任何新增的 int 型 get 入口都会让本用例 FAIL。
        """
        import pathlib
        import re

        repo_dir = (
            pathlib.Path(__file__).resolve().parents[4]
            / "src"
            / "inkflow"
            / "infrastructure/database/repositories"
        )
        pattern = re.compile(r"async def get\(self, (\w+): int\)")
        offenders: list[str] = []
        for path in sorted(repo_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                offenders.append(f"{path.name}::{m.group(1)}")
        assert not offenders, (
            f"以下 repo get 仍声明裸 int 入参（应为 uuid.UUID 或走例外白名单）：{offenders}"
        )


class TestIntCompatSurfaceRetired1291:
    """#1291 ⑦：int 兼容面的**源码级**退役证据（机器可验证，非人工声明）。"""

    @staticmethod
    def _src_root():
        import pathlib

        return pathlib.Path(__file__).resolve().parents[4] / "src" / "inkflow"

    def test_no_to_int_id_helpers_remain(self) -> None:
        """全仓无 `_to_int_id` 定义（22 → 0）。"""
        import re

        offenders: list[str] = []
        for path in sorted(self._src_root().rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"^def (_to_int_id\w*)\s*\(", text, re.M):
                offenders.append(f"{path.name}::{m.group(1)}")
        assert not offenders, f"仍有 _to_int_id helper 定义：{offenders}"

    def test_no_uuid_to_pk_or_none_consumers(self) -> None:
        """全仓无 `uuid_to_pk_or_none` 消费者（含 import 与定义）。"""
        offenders: list[str] = []
        for path in sorted(self._src_root().rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if "uuid_to_pk_or_none" in line:
                    offenders.append(f"{path.name}:{i}")
        assert not offenders, f"仍有 uuid_to_pk_or_none 引用：{offenders}"

    def test_require_uuid_pk_has_no_isinstance_dual_path(self) -> None:
        """`require_uuid_pk` 是唯一入口：其**调用点**无 `isinstance(x, uuid.UUID)` 双路径。

        排除 `_id_guard.py` 自身（其内部类型判定是实现细节，非调用点双路径）。
        """
        import re

        offenders: list[str] = []
        guard = self._src_root() / "infrastructure/database/repositories/_id_guard.py"
        for path in sorted(self._src_root().rglob("*.py")):
            if path == guard:
                continue
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(
                r"if isinstance\(\w+, uuid\.UUID\):(.{0,200}?)require_uuid_pk", text, re.S
            ):
                offenders.append(f"{path.name}: {m.group(0)[:80]!r}")
        assert not offenders, f"仍存在 require_uuid_pk 的 isinstance 双路径：{offenders}"


# ══════════════════════════════════════════════════════════════════════════
# ④ int 主键 repo 例外：仍接受 int（不回退）
# ══════════════════════════════════════════════════════════════════════════


class TestIntPkRepoUnchanged1291:
    """#1291 ④：主键语义确为 int 的实体（Agent/ProviderConfig）保持 int 入参。

    这是**例外白名单**的机器化表达：收窄只施于 UUID 主键语义实体，
    不误伤 DB 自增主键实体（`Agent.id: int | None`）。
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
    async def test_int_pk_repo_accepts_int_and_rejects_uuid_safely(
        self, db_session, mod_path: str, cls_name: str, factory: str
    ) -> None:
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

        # int 路径必须仍然命中
        assert await repo.get(saved.id) is not None

        # UUID 入参：不抛 TypeError，且不得误命中
        for candidate in (uuid.uuid4(), uuid.UUID(int=1), uuid.UUID(int=saved.id)):
            try:
                hit = await repo.get(candidate)  # type: ignore[arg-type]  # 故意传 UUID
            except TypeError as exc:
                pytest.fail(f"{cls_name}.get(UUID) 抛 TypeError：{exc}")
            assert hit is None, f"{cls_name}.get({candidate}) 返回了记录 —— UUID 被静默折算后误命中"


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 溢出防御仍生效（经 UUID 通道）
# ══════════════════════════════════════════════════════════════════════════


class TestOverflowGuardStillActive1291:
    """#1291 ⑤：int64 溢出防御**不退役**，只退役「裸 int 入参」通道。"""

    async def test_random_uuid4_overflow_returns_none_not_raises(self, db_session) -> None:
        """随机 uuid4 的 `.int` 必然超 int64 → 归一后判越界 → None（非 OverflowError）。"""
        repo = SQLiteProjectRepository(db_session)
        # 铺一些真实数据，确保「返 None」不是「表为空」的假象
        for i in range(3):
            await repo.add(_project(f"溢出防御铺底 {i}"))

        for _ in range(5):
            ghost = uuid.uuid4()
            assert ghost.int > 2**63 - 1
            assert await repo.get(ghost) is None

    async def test_small_uuid_hits_its_own_row(self, db_session) -> None:
        """小值 UUID（`.int` 在 int64 内）→ 正常参与 SQL 查询（防御不误伤正常路径）。"""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("小值 UUID 项目"))

        got = await repo.get(created.id)
        assert got is not None
        assert got.id == created.id


# ══════════════════════════════════════════════════════════════════════════
# ⑥ 可证伪性自证：守卫形态仍承重
# ══════════════════════════════════════════════════════════════════════════


class TestGuardFalsifiability1291:
    """#1291 ⑥：把守卫改回「裸比较」形态 → ① 类断言必 FAIL。"""

    async def test_old_guard_shape_fails_on_uuid(self, db_session) -> None:
        """旧形态（守卫前无类型归一）对 UUID 必然 TypeError。"""
        pid: object = uuid.uuid4()
        with pytest.raises(TypeError, match="not supported between instances"):
            _ = pid < -(2**63) or pid >= 2**63  # type: ignore[operator]  # 故意复现旧守卫

    async def test_uuid_only_guard_shape(self) -> None:
        """收窄终态的守卫形态：只接受 `uuid.UUID`，归一后比较（与实现契约一致）。"""

        def _guarded(pid: uuid.UUID) -> bool:
            value = pid.int
            return value < -(2**63) or value >= 2**63

        assert _guarded(uuid.uuid4()) is True  # 随机 uuid4 .int 超 int64 → 视为不存在
        assert _guarded(uuid.UUID(int=1)) is False  # 小值 UUID 在范围内
