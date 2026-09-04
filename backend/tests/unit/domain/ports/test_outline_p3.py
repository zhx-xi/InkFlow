"""F43 P3 大纲三级 + 章关联后端 RED 契约测试（spec §2.8/§3.6/§9.7 O 系列，OB1-OB11）.

只写契约测试，不实现 src/。GREEN 必实现清单（本文件 docstring 即契约载体）:
- domain/models/outline.py: Outline/OutlineCreate 加 level: str = "chapter"、
  parent_id: uuid.UUID | None = None、chapter_id: uuid.UUID | None = None；
  OutlineUpdate 加 level: str | None = None、parent_id: uuid.UUID | str | None = None
  （"" 清除）、chapter_id: uuid.UUID | str | None = None（"" 清除）
- domain/ports/outline_errors.py: OutlineLevelError / OutlineHierarchyError /
  OutlineChapterRefError（OutlineServiceError 子类，422 映射）
- domain/services/outline_service.py: create_outline 加 level/parent_id/chapter_id
  参数（默认值向后兼容）；层级校验（overall 禁 parent；volume 父须 level=overall 同项目；
  chapter 父须 level=volume 同项目；parent 空 = 孤立章合法）；chapter_id 仅
  level=chapter 可设 + 指向章节须存在且同项目（OutlineService.__init__ 加
  chapter_repo: ChapterRepositoryProtocol | None = None 可选注入，deps.py 传真实 repo）
- api/routers/outlines.py: OutlineCreateBody 加 level/parent_id/chapter_id 并透传
  （kwargs 形态 level=.../parent_id=.../chapter_id=...）；PATCH 透传 OutlineUpdate
  （parent_id="" / chapter_id="" 由 service 转 None 清除）
- infrastructure: OutlineORM 加 level（VARCHAR(16) DEFAULT 'chapter'）/parent_id
  （INTEGER 自引用 FK outlines.id SET NULL）/chapter_id（INTEGER FK chapters.id
  SET NULL）三列 + repo 双向映射透传；core/database.py 加 ensure_outline_columns(conn)
  迁移（旧表加三列 + 幂等 + 表不存在 no-op）

RED 预期形态（四层失败类别地图，规则 1q；整文件可收集，零收集 ERROR）:
- OB1/OB2/OB10 models 层: Pydantic extra='ignore' 静默丢字段 → model_dump()["level"]
  KeyError / 非法 level 构造不报错 → pytest.raises DID NOT RAISE
- OB3-OB8 service 层: create_outline 无新 kwarg → TypeError（OB6/OB7 为
  _make_service 传 chapter_repo → __init__ TypeError，docstring 已注明）
- OB9 api 层: create_outline mock 断言缺新 kwargs → AssertionError；PATCH 断言
  update_arg.parent_id → AttributeError
- OB11 database: ensure_outline_columns 缺失 → 用例体 lazy import ImportError
  （FAILED 形态，非收集 ERROR，规则 1c 混合轨）

依据: specs/f43-setting-library-gui/spec.md §2.8/§3.6/§9.7。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 缺失错误类 stub（置主 import 前，规则 1h）: RED 阶段 ImportError → 模块级 stub；
# GREEN 建真实类后 try import 命中，stub 分支不再执行。OutlineLevelError 仅 docstring
# 钉死（OB2 走 models 层 ValueError/ValidationError，不直接引用该符号，免 F401）。
try:
    from inkflow.domain.ports.outline_errors import (
        OutlineChapterRefError,
        OutlineHierarchyError,
        OutlineLevelError,
    )
except ImportError:  # RED 阶段: F43 P3 新错误类未实现 → stub（GREEN 建真实类替换）

    class OutlineChapterRefError(Exception):
        """F43 P3 章关联引用错误 stub（GREEN 建真实类替换）."""

    class OutlineHierarchyError(Exception):
        """F43 P3 层级约束错误 stub（GREEN 建真实类替换）."""

    class OutlineLevelError(Exception):
        """F43 P3 层级非法错误 stub（GREEN 建真实类替换）."""


from inkflow.api.app import app
from inkflow.core.database import Base
from inkflow.domain.models.outline import Outline, OutlineCreate, OutlineUpdate
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.services.outline_service import OutlineService
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    level: str = "chapter",
    parent_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用大纲实体（固定时间戳；三级字段透传——RED 阶段被 extra='ignore' 丢弃）."""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        level=level,
        parent_id=parent_id,
        chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合（OB11 迁移断言用）."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 默认全方法可用（显式默认值，规则 1m）."""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_chapter_repo() -> MagicMock:
    """Mock ChapterRepositoryProtocol — chapter_id 存在性校验（OB6/OB7 注入）."""
    repo = MagicMock(spec=ChapterRepositoryProtocol)
    repo.get_chapter = AsyncMock(return_value=None)
    return repo


def _make_service(repo: MagicMock, chapter_repo: MagicMock | None = None) -> OutlineService:
    """构造被测 OutlineService（全 Mock 注入；chapter_repo 可选扩展注入）.

    RED 形态: __init__ 未扩展 chapter_repo 参数 → TypeError: unexpected keyword
    argument（OB6/OB7 签名扩展 RED，属合法，规则 1q 失败地图 service 层）。
    """
    if chapter_repo is None:
        return OutlineService(repository=repo)
    return OutlineService(repository=repo, chapter_repo=chapter_repo)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock OutlineService（镜像 test_outline_api.py 模式）."""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestOutlineP3Models:
    """OB1/OB2: models 层三级字段契约."""

    def test_ob1_models_have_hierarchy_fields(self) -> None:
        """OB1 models：Outline/OutlineCreate/OutlineUpdate 含 level/parent_id/chapter_id 字段.

        默认值 chapter/None/None。RED 预期: Pydantic v2 extra='ignore' 静默丢字段
        → Outline 构造不报错，但 model_dump() 无 level 键 → KeyError（模型层失败形态）。
        GREEN 必实现: Outline/OutlineCreate level: str = "chapter"、
        parent_id: uuid.UUID | None = None、chapter_id: uuid.UUID | None = None；
        OutlineUpdate level: str | None = None、parent_id: uuid.UUID | str | None = None、
        chapter_id: uuid.UUID | str | None = None。
        """
        outline = _outline("整体大纲")
        dumped = outline.model_dump()
        assert dumped["level"] == "chapter"  # RED: KeyError
        assert dumped["parent_id"] is None
        assert dumped["chapter_id"] is None

        create = OutlineCreate(project_id=PID, name="整体大纲")
        create_dump = create.model_dump()
        assert create_dump["level"] == "chapter"
        assert create_dump["parent_id"] is None
        assert create_dump["chapter_id"] is None

        update = OutlineUpdate(name="改名")
        update_dump = update.model_dump()
        assert update_dump["level"] is None
        assert update_dump["parent_id"] is None
        assert update_dump["chapter_id"] is None

    def test_ob2_models_level_invalid_raises(self) -> None:
        """OB2 models：level 非法值 → 校验错误（ValueError 或 Pydantic ValidationError）.

        RED 预期: OutlineCreate 无 level 字段（extra='ignore' 丢弃）→ 构造不报错 →
        pytest.raises 未触发 → FAILED（DID NOT RAISE）。
        GREEN 必实现: level ∈ {overall, volume, chapter} 校验；非法 → ValueError/
        ValidationError（service 层映射 OutlineLevelError → 422，docstring 契约）。
        """
        with pytest.raises((ValueError, ValidationError)):
            OutlineCreate(project_id=PID, name="非法层级", level="bogus")

    def test_ob2c_outline_update_level_validation(self) -> None:
        """OB2c models：OutlineUpdate level 合法/显式 None/非法（覆盖 validate_level 286-288）."""
        assert OutlineUpdate(name="x", level="volume").level == "volume"
        assert OutlineUpdate(name="x", level=None).level is None
        with pytest.raises((ValueError, ValidationError)):
            OutlineUpdate(name="x", level="bogus")


class TestOutlineP3Service:
    """OB3-OB8: service 层层级/章关联校验契约（全 Mock repo 轨）."""

    @pytest.mark.asyncio
    async def test_ob3_service_overall_with_parent_raises_hierarchy(self, mock_repo) -> None:
        """OB3 service：create_outline(level="overall", parent_id=非空) → OutlineHierarchyError.

        RED 预期: 当前 create_outline 签名无 level/parent_id 参数 → TypeError:
        unexpected keyword argument（service 层签名扩展失败形态）。
        GREEN 必实现: create_outline 加 level/parent_id/chapter_id 参数（默认值向后兼容）；
        overall + parent_id 非空 → OutlineHierarchyError（422）。
        """
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "整体大纲", level="overall", parent_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_ob4_service_volume_parent_not_overall_raises_hierarchy(self, mock_repo) -> None:
        """OB4 service：create_outline(level="volume", parent 非 overall) → OutlineHierarchyError.

        RED 预期: create_outline 无 level/parent_id 参数 → TypeError（service 层失败形态）。
        GREEN 必实现: repository.get(parent_id) 查父大纲；父 level != "overall"
        （或不存在）→ OutlineHierarchyError（422）。
        """
        parent = _outline("卷一", level="volume")
        mock_repo.get = AsyncMock(return_value=parent)
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "卷甲", level="volume", parent_id=parent.id)

    @pytest.mark.asyncio
    async def test_ob5_service_chapter_parent_not_volume_raises_hierarchy(self, mock_repo) -> None:
        """OB5 service：create_outline(level="chapter", parent 非 volume) → OutlineHierarchyError.

        RED 预期: create_outline 无 level/parent_id 参数 → TypeError（service 层失败形态）。
        GREEN 必实现: repository.get(parent_id) 查父大纲；父 level != "volume"
        （或不存在）→ OutlineHierarchyError（422）；parent 空 = 孤立章（合法，OB8）。
        """
        parent = _outline("整体一", level="overall")
        mock_repo.get = AsyncMock(return_value=parent)
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "章甲", level="chapter", parent_id=parent.id)

    @pytest.mark.asyncio
    async def test_ob6_service_chapter_id_missing_raises_ref_error(
        self, mock_repo, mock_chapter_repo
    ) -> None:
        """OB6 service：create_outline chapter_id=不存在章节 → OutlineChapterRefError.

        RED 预期: _make_service 传 chapter_repo → __init__ 未扩展 → TypeError
        （service 层失败形态）。
        GREEN 必实现: OutlineService.__init__ 加 chapter_repo（可选注入，默认 None）；
        chapter_id 非空 → chapter_repo.get_chapter(chapter_id) 为 None（不存在/
        跨项目）→ OutlineChapterRefError（422）。
        """
        parent = _outline("卷一", level="volume")
        mock_repo.get = AsyncMock(return_value=parent)
        svc = _make_service(mock_repo, mock_chapter_repo)  # RED: TypeError
        with pytest.raises(OutlineChapterRefError):
            await svc.create_outline(
                PID, "章甲", level="chapter", parent_id=parent.id, chapter_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_ob7_service_overall_with_chapter_id_raises_ref_error(
        self, mock_repo, mock_chapter_repo
    ) -> None:
        """OB7 service：create_outline(level="overall", chapter_id=非空) → OutlineChapterRefError.

        RED 预期: _make_service 传 chapter_repo → __init__ 未扩展 → TypeError
        （service 层失败形态）。
        GREEN 必实现: chapter_id 非空且 level != "chapter" → OutlineChapterRefError
        （422，无需查库；仅 chapter 可关联写作章节）。
        """
        svc = _make_service(mock_repo, mock_chapter_repo)  # RED: TypeError
        with pytest.raises(OutlineChapterRefError):
            await svc.create_outline(PID, "整体一", level="overall", chapter_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_ob8_service_orphan_chapter_rejected(self, mock_repo) -> None:
        """OB8 service：孤立章（level="chapter", parent_id=None）→ 422（#835 强制树形）.

        RED 预期（迁移自「孤立章合法创建」）: 当前实现允许孤立章，pytest.raises 未触发
        → 用例 FAIL（真 RED）。GREEN 必实现: chapter + parent 空 → OutlineHierarchyError
        （章必须挂卷）；合法树（overall→volume→chapter）仍可创建。
        """
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "孤立章", level="chapter", parent_id=None)

    @pytest.mark.asyncio
    async def test_ob2b_service_invalid_level_raises_level_error(self, mock_repo) -> None:
        """OB2b service：create_outline(level="invalid") → OutlineLevelError（覆盖 L156/L99）."""
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineLevelError):
            await svc.create_outline(PID, "非法层级", level="invalid")

    @pytest.mark.asyncio
    async def test_ob4b_service_parent_not_found_raises_hierarchy(self, mock_repo) -> None:
        """OB4b service：volume + parent 不存在 → OutlineHierarchyError（覆盖 L162）."""
        mock_repo.get = AsyncMock(return_value=None)
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "卷甲", level="volume", parent_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_ob9b_service_update_clears_parent_and_chapter(self, mock_repo) -> None:
        """OB9b service：update 清除 chapter 的 parent_id/chapter_id → 422（#835，孤立章非法）.

        RED 预期（迁移）: 当前实现清除后放行 → pytest.raises 未触发 → 用例 FAIL（真 RED）。
        GREEN 必实现: chapter + parent 清空 → OutlineHierarchyError（章必须挂卷）；
        合法更新（仅改 level=overall/不 orphan）仍放行。
        """
        existing = _outline(
            "章甲", level="chapter", parent_id=uuid.uuid4(), chapter_id=uuid.uuid4()
        )
        mock_repo.get = AsyncMock(return_value=existing)
        svc = _make_service(mock_repo)
        update = OutlineUpdate(parent_id="", chapter_id="")
        with pytest.raises(OutlineHierarchyError):
            await svc.update_outline(existing.id, update)


class TestOutlineP3API:
    """OB9: 大纲端点 level/parent_id/chapter_id 透传（Mock Service 层）."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_ob9_api_create_and_patch_passthrough(self, mock_get_svc: MagicMock) -> None:
        """OB9 api：POST 透传 level/parent_id/chapter_id；PATCH 透传 + "" 清除语义.

        RED 预期: ① POST 断言 create_outline 收到 level/parent_id/chapter_id kwargs →
        当前 router 只传 4 位置参 → AssertionError（api 层 mock 断言缺参形态）；
        ② PATCH 断言 update_arg.parent_id == "" → OutlineUpdate 无 parent_id 字段 →
        AttributeError（模型层失败形态，PATCH 部分 GREEN 后验证）。
        GREEN 必实现: OutlineCreateBody 加 level（默认 chapter）/parent_id/chapter_id +
        create 调用以 kwargs 形态透传（level=.../parent_id=.../chapter_id=...，契约裁定
        kwargs 锁形态，位置传参必破）；PATCH 透传 OutlineUpdate（parent_id="" /
        chapter_id="" 由 service 转 None 清除）。
        """
        svc = _mock_svc(mock_get_svc)
        outline = _outline("卷甲")
        svc.create_outline = AsyncMock(return_value=outline)
        svc.update_outline = AsyncMock(return_value=outline)

        parent_id = uuid.uuid4()
        response = client.post(
            f"/api/v1/projects/{PID}/outlines",
            json={"name": "卷甲", "level": "volume", "parent_id": str(parent_id)},
        )
        assert response.status_code == 201
        svc.create_outline.assert_awaited_once_with(
            PID, "卷甲", "", 0, level="volume", parent_id=parent_id, chapter_id=None
        )  # RED: AssertionError

        oid = uuid.uuid4()
        resp2 = client.patch(f"/api/v1/outlines/{oid}", json={"parent_id": ""})
        assert resp2.status_code == 200
        update_arg = svc.update_outline.call_args.args[1]
        assert update_arg.parent_id == ""  # RED: AttributeError（OutlineUpdate 无 parent_id 字段）
        assert "parent_id" in update_arg.model_fields_set


@pytest.mark.integration
class TestOutlineP3Repo:
    """OB10: Outline ORM ↔ 领域往返（真实 in-memory SQLite，镜像 test_outline_repo.py 模式）."""

    @pytest.fixture
    async def db_session(self):
        """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）."""
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

    @pytest.fixture
    async def project(self, db_session):
        """一个基础项目（大纲/章节的 FK 依赖）."""
        p = ProjectORM(name="测试项目")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)
        return p

    async def test_ob10_repo_roundtrip_with_hierarchy_fields(self, db_session, project):
        """OB10 repo：Outline ORM ↔ 领域往返含 level/parent_id/chapter_id.

        RED 预期: 领域 Outline 无 level/parent_id/chapter_id 字段（extra='ignore'
        静默丢弃）+ ORM 无对应列 → repo.add 不报错但字段丢失 → 读回断言
        model_dump()["level"] → KeyError（模型层失败形态）。
        GREEN 必实现: OutlineORM 加 level（VARCHAR(16) DEFAULT 'chapter'）/parent_id
        （INTEGER，自引用 FK outlines.id SET NULL）/chapter_id（INTEGER，FK chapters.id
        SET NULL）三列 + repo 双向映射透传（level 直传；parent_id/chapter_id UUID ↔ int）。
        """
        repo = SQLiteOutlineRepository(db_session)
        parent = await repo.add(
            _outline("第一卷", project_id=uuid.UUID(int=project.id), level="volume")
        )

        # 真实写作章节行（chapter_id FK 目标）
        chapter_orm = ChapterORM(project_id=project.id, title="第一章 试剑大典")
        db_session.add(chapter_orm)
        await db_session.commit()
        await db_session.refresh(chapter_orm)

        child = await repo.add(
            _outline(
                "试剑大典",
                project_id=uuid.UUID(int=project.id),
                level="chapter",
                parent_id=parent.id,
                chapter_id=uuid.UUID(int=chapter_orm.id),
            )
        )

        got = await repo.get(child.id.int)
        assert got is not None
        dumped = got.model_dump()
        assert dumped["level"] == "chapter"  # RED: KeyError
        assert dumped["parent_id"] == parent.id
        assert dumped["chapter_id"] == uuid.UUID(int=chapter_orm.id)


class TestOutlineP3Database:
    """OB11: ensure_outline_columns 迁移契约（真 SQLite 同步轨）."""

    def test_ob11_database_ensure_outline_columns_migration(self) -> None:
        """OB11 database：ensure_outline_columns 迁移（旧表加列 + 幂等 + 表不存在 no-op）.

        RED 预期: inkflow.core.database 无 ensure_outline_columns → 用例体 lazy
        import → ImportError（FAILED 形态，非收集 ERROR，规则 1c 混合轨）。
        GREEN 必实现: ensure_outline_columns(conn)——PRAGMA table_info(outlines) →
        无 level → ALTER ADD COLUMN level VARCHAR(16) DEFAULT 'chapter'；
        无 parent_id → ALTER ADD COLUMN parent_id INTEGER；无 chapter_id →
        ALTER ADD COLUMN chapter_id INTEGER；表不存在（全新环境）→ no-op，等
        create_all 建新表（spec §2.8 迁移，接线点在 create_tables() 后）。
        """
        from inkflow.core.database import ensure_outline_columns  # RED: ImportError

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE outlines (id INTEGER PRIMARY KEY, project_id INTEGER, "
                    "name TEXT, description TEXT, sort_order INTEGER, extra JSON, "
                    "created_at DATETIME, updated_at DATETIME)"
                )
            )
            conn.commit()

            ensure_outline_columns(conn)
            conn.commit()
            cols = _cols(conn, "outlines")
            assert {"level", "parent_id", "chapter_id"} <= cols

            # 幂等：二次调用不抛错且列集合不变
            ensure_outline_columns(conn)
            conn.commit()
            assert _cols(conn, "outlines") == cols

        # 表不存在（全新环境）→ no-op 不抛错
        fresh = create_engine("sqlite:///:memory:")
        with fresh.connect() as conn:
            ensure_outline_columns(conn)
