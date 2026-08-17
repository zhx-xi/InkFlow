"""F45 M2 语义总结仓储 RED 契约测试 — SQLiteSemanticSummaryRepository（真实 in-memory SQLite 轨）.

依据: specs/f45-memory-evolution/spec.md §2.3（SemanticSummary 模型）/
§2.4（semantic_summaries 表列）/§5.3（LLM 总结管线）/§5.4（anchor_hash
幂等）/§8 M2 文件表 + §9 测试策略 + §13 M2-3 验收，父侧定稿契约同源
（test_semantic_summary_repo.py docstring 即契约载体，镜像 F45 M1
test_user_preference_repo.py 真实 SQLite 形态）。

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.semantic_summary_repo import (
        SQLiteSemanticSummaryRepository,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLiteSemanticSummaryRepository（infrastructure/database/repositories/
   semantic_summary_repo.py 新建，异步 SQLAlchemy，构造签名
   `SQLiteSemanticSummaryRepository(db_session: AsyncSession)`，镜像 M1
   SQLiteUserPreferenceRepository 模式）:

       class SQLiteSemanticSummaryRepository:
           async def upsert(self, summary: SemanticSummary) -> SemanticSummary:
               # 按 (scope, project_id) 查找：存在 → 更新 content/anchor_hash/
               # anchor_count/model/updated_at（created_at 保留）并返回；
               # 不存在 → 插入新行返回。
           async def get(self, scope, project_id=None) -> SemanticSummary | None:
               # scope=USER 时 project_id 传 None 查全局记录（§5.3 全局单一性）。
           async def list_all(self, scope=None) -> tuple[list[SemanticSummary], int]:
               # scope 可空过滤；排序 created_at asc；返回 (列表, 总数)。
           async def delete_by_project(self, project_id) -> int:
               # 删除 scope=project 且 project_id 匹配的行，返回删除行数
               # （项目删除级联清理用，spec §7 边界表）。

   语义: upsert 幂等——同 (scope, project_id) 更新不新增（用户级全局仅一份）；
   get 按 (scope, project_id) 精确匹配（USER 层 project_id=None）；
   delete_by_project 只删项目级行（scope=user 行不受影响）。

2. 领域 SemanticSummary/SummaryScope（domain/models/semantic_summary.py
   新建，Pydantic + StrEnum，model_config={"from_attributes": True}，
   镜像 F28 ProjectPreference / M1 UserPreference）:

       class SummaryScope(StrEnum):
           PROJECT = "project"      # 项目级风格偏好（称谓规则/结构习惯/文风）
           USER = "user"            # 用户级通用风格（句长/冗余/叙述对话比例）

       class SemanticSummary(BaseModel):
           id: str
           scope: SummaryScope
           project_id: uuid.UUID | None = None
           content: str
           anchor_hash: str
           anchor_count: int
           model: str
           created_at: datetime
           updated_at: datetime

3. ORM（infrastructure/database/models/semantic_summary.py 新建，
   SemanticSummaryORM）: semantic_summaries 表列（spec §2.4）— id(String36
   PK default uuid4) / scope(String20) / project_id(String36 nullable) /
   content(Text) / anchor_hash(String64) / anchor_count(Integer) /
   model(String100) / created_at / updated_at。project_id 无 FK（镜像
   user_preferences 先例——projects 主键为 int 自增，String(36) uuid 值
   与 int 主键永远不匹配）；scope=user 时 project_id=None。

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items /
1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.semantic_summary_repo'
顶部仅 import 主契约模块（semantic_summary_repo）；domain models / ORM
models 全部惰性（fixture 与用例体内 import）——RED 阶段同批 CREATE 尚未
落地，收集错误保持聚焦主模块（规则 1l）。

asyncio 模式: 本 venv pytest-asyncio mode=Mode.AUTO（pyproject
asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.repositories.semantic_summary_repo import (
    SQLiteSemanticSummaryRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PROJECT_ID_2 = uuid.UUID("87654321-4321-8765-4321-876543218765")
PROJECT_ID_3 = uuid.UUID("abcdefab-1234-4abc-8def-abcdefabcdef")
LLM_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"  # #415 拍板：配置文件唯一默认源


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（SemanticSummaryORM），否则 create_all 不建 semantic_summaries 表.
    """

    # 惰性：RED 阶段模块未实现（create_all 前注册表——load-bearing）
    from inkflow.infrastructure.database.models.semantic_summary import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（create_all 需要）
        SemanticSummaryORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_summary(
    *,
    scope,
    project_id=None,
    content="叙述偏好：称呼主角用全名「林晚」而非代词",
    anchor_hash="sha256-anchor-hash-1",
    anchor_count=5,
    model=LLM_DEFAULT_MODEL,
    summary_id=None,
):
    """构造 SemanticSummary 领域对象（惰性 import；id 缺省 uuid4 字符串）."""
    from inkflow.domain.models.semantic_summary import SemanticSummary

    now = datetime.now(UTC)
    return SemanticSummary(
        id=summary_id or str(uuid.uuid4()),
        scope=scope,
        project_id=project_id,
        content=content,
        anchor_hash=anchor_hash,
        anchor_count=anchor_count,
        model=model,
        created_at=now,
        updated_at=now,
    )


async def _create_summary(repo, *, scope, project_id=None, **kw):
    """经 repo.upsert 落库一条语义总结（scope 传 SummaryScope 枚举）."""
    summary = _make_summary(scope=scope, project_id=project_id, **kw)
    return await repo.upsert(summary)


async def _insert_summary_direct(
    db_session,
    *,
    scope,
    project_id,
    content,
    anchor_hash,
    created_at,
):
    """直插显式时间（repo.upsert 不保留显式 created_at——更新路径断言用）."""
    from inkflow.infrastructure.database.models.semantic_summary import (
        SemanticSummaryORM,
    )

    await db_session.execute(
        insert(SemanticSummaryORM).values(
            scope=scope,
            project_id=str(project_id) if project_id is not None else None,
            content=content,
            anchor_hash=anchor_hash,
            anchor_count=5,
            model=LLM_DEFAULT_MODEL,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await db_session.commit()


@pytest.mark.integration
class TestSQLiteSemanticSummaryRepository:
    """SQLiteSemanticSummaryRepository 集成测试（真实 in-memory SQLite 轨）."""

    async def test_upsert_creates_new(self, db_session):
        """契约①: upsert 新 summary → 落库，id/scope/project_id/content/anchor_hash
        往返正确（经 get 读回等值）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        result = await repo.upsert(
            _make_summary(
                scope=SummaryScope.PROJECT,
                project_id=PROJECT_ID,
                content="叙述偏好：称呼主角用全名「林晚」而非代词",
                anchor_hash="sha256-proj-1",
                anchor_count=5,
                model=LLM_DEFAULT_MODEL,
            )
        )

        assert isinstance(result.id, str)
        assert len(result.id) == 36
        assert result.scope == SummaryScope.PROJECT
        assert result.project_id == PROJECT_ID
        assert result.content == "叙述偏好：称呼主角用全名「林晚」而非代词"
        assert result.anchor_hash == "sha256-proj-1"
        assert result.anchor_count == 5
        assert result.model == LLM_DEFAULT_MODEL
        assert isinstance(result.created_at, datetime)
        assert isinstance(result.updated_at, datetime)

        # 持久化验证：读回
        fetched = await repo.get(SummaryScope.PROJECT, PROJECT_ID)
        assert fetched is not None
        assert fetched.id == result.id
        assert fetched.scope == SummaryScope.PROJECT
        assert fetched.project_id == PROJECT_ID
        assert fetched.content == result.content
        assert fetched.anchor_hash == result.anchor_hash
        assert fetched.anchor_count == result.anchor_count
        assert fetched.model == result.model

    async def test_upsert_updates_existing(self, db_session):
        """契约②: 同 (scope, project_id) 再 upsert（content/hash 变化）→ 更新不新增
        （list_all 总数仍 1；content 为新值；created_at 保留、updated_at 变化）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        old_ts = datetime(2026, 8, 1, 10, 0, 0)
        await _insert_summary_direct(
            db_session,
            scope="project",
            project_id=PROJECT_ID,
            content="旧项目总结",
            anchor_hash="old-hash",
            created_at=old_ts,
        )

        result = await repo.upsert(
            _make_summary(
                scope=SummaryScope.PROJECT,
                project_id=PROJECT_ID,
                content="新项目总结：叙述偏好用角色全名",
                anchor_hash="new-hash",
                anchor_count=6,
            )
        )

        assert result.content == "新项目总结：叙述偏好用角色全名"
        assert result.anchor_hash == "new-hash"
        assert result.anchor_count == 6
        assert result.created_at == old_ts  # created_at 保留（既有行时间）
        assert result.updated_at > old_ts  # updated_at 变化（onupdate 刷新）
        # 更新不新增：全表仅 1 行
        items, total = await repo.list_all()
        assert total == 1
        assert items[0].content == "新项目总结：叙述偏好用角色全名"
        fetched = await repo.get(SummaryScope.PROJECT, PROJECT_ID)
        assert fetched is not None
        assert fetched.content == "新项目总结：叙述偏好用角色全名"

    async def test_upsert_user_scope_singleton(self, db_session):
        """契约③: scope=USER project_id=None 多次 upsert → 全局仅一条（§5.3
        用户级总结全局单一性），更新路径保留既有行 id 不变."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        first = await repo.upsert(
            _make_summary(
                scope=SummaryScope.USER,
                project_id=None,
                content="用户通用风格 v1",
                anchor_hash="user-hash-1",
                anchor_count=3,
            )
        )
        second = await repo.upsert(
            _make_summary(
                scope=SummaryScope.USER,
                project_id=None,
                content="用户通用风格 v2",
                anchor_hash="user-hash-2",
                anchor_count=4,
            )
        )
        third = await repo.upsert(
            _make_summary(
                scope=SummaryScope.USER,
                project_id=None,
                content="用户通用风格 v3",
                anchor_hash="user-hash-3",
                anchor_count=5,
            )
        )

        items, total = await repo.list_all(scope=SummaryScope.USER)
        assert total == 1
        assert items[0].content == "用户通用风格 v3"  # 最新内容
        assert second.id == first.id  # 更新路径保留既有行 id（非新增）
        assert third.id == first.id
        fetched = await repo.get(SummaryScope.USER, None)
        assert fetched is not None
        assert fetched.content == "用户通用风格 v3"

    async def test_get_by_scope_and_project(self, db_session):
        """契约④: get(PROJECT, pid) 命中；get(USER, None) 命中；scope/project_id
        不匹配 → None（(scope, project_id) 联合精确匹配）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID,
            content="项目 A 风格",
            anchor_hash="hash-a",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID_2,
            content="项目 B 风格",
            anchor_hash="hash-b",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.USER,
            project_id=None,
            content="用户通用风格",
            anchor_hash="hash-u",
        )

        assert (await repo.get(SummaryScope.PROJECT, PROJECT_ID)).content == "项目 A 风格"
        assert (await repo.get(SummaryScope.PROJECT, PROJECT_ID_2)).content == "项目 B 风格"
        assert (await repo.get(SummaryScope.USER, None)).content == "用户通用风格"
        # 不匹配 → None
        assert (await repo.get(SummaryScope.PROJECT, None)) is None
        assert (await repo.get(SummaryScope.USER, PROJECT_ID)) is None
        assert (await repo.get(SummaryScope.PROJECT, PROJECT_ID_3)) is None

    async def test_list_all_scope_filter(self, db_session):
        """契约⑤: list_all() 全量；list_all(scope=PROJECT) 过滤；list_all(scope=USER)
        过滤（total 与列表一致）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID,
            content="P1",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID_2,
            content="P2",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.USER,
            project_id=None,
            content="U1",
        )

        items, total = await repo.list_all()
        assert total == 3
        assert {s.content for s in items} == {"P1", "P2", "U1"}

        proj_items, proj_total = await repo.list_all(scope=SummaryScope.PROJECT)
        assert proj_total == 2
        assert all(s.scope == SummaryScope.PROJECT for s in proj_items)

        user_items, user_total = await repo.list_all(scope=SummaryScope.USER)
        assert user_total == 1
        assert user_items[0].content == "U1"

    async def test_delete_by_project(self, db_session):
        """契约⑥: 删除 scope=project 匹配行返回删除数；scope=user 行不受影响；
        不匹配 → 0."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.semantic_summary import SummaryScope

        repo = SQLiteSemanticSummaryRepository(db_session)
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID,
            content="P1",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID_2,
            content="P2",
        )
        await _create_summary(
            repo,
            scope=SummaryScope.USER,
            project_id=None,
            content="U1",
        )

        deleted = await repo.delete_by_project(PROJECT_ID)

        assert deleted == 1
        assert (await repo.get(SummaryScope.PROJECT, PROJECT_ID)) is None
        assert (await repo.get(SummaryScope.PROJECT, PROJECT_ID_2)).content == "P2"
        assert (await repo.get(SummaryScope.USER, None)).content == "U1"  # 用户级不受影响
        _, total = await repo.list_all()
        assert total == 2
        # 不匹配 → 0
        assert (await repo.delete_by_project(PROJECT_ID_3)) == 0


async def test_orm_repr_includes_id_and_content() -> None:
    """覆盖 SemanticSummaryORM.__repr__（coverage 门禁 models/semantic_summary.py，
    镜像 M1 test_orm_repr_includes_id_and_pattern 形态）."""
    from inkflow.infrastructure.database.models.semantic_summary import (
        SemanticSummaryORM,
    )

    orm = SemanticSummaryORM(
        scope="project",
        project_id=str(PROJECT_ID),
        content="叙述偏好：称呼主角用全名「林晚」而非代词",
        anchor_hash="hash-1",
        anchor_count=5,
        model=LLM_DEFAULT_MODEL,
    )
    text = repr(orm)
    assert "SemanticSummaryORM" in text
    assert "叙述偏好" in text
