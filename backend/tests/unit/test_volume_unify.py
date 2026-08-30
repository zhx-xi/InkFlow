"""卷数据模型统一 — Volume(分组) 与 卷纲(Outline level=volume) 显式关联 RED 契约测试.

只写契约测试，不实现 src/。GREEN 必实现清单（本文件 docstring 即契约载体）:
- domain/models/outline.py: Outline/OutlineCreate 加 volume_id: uuid.UUID | None = None；
  OutlineUpdate 加 volume_id: uuid.UUID | str | None = None（"" 清除，镜像 chapter_id）
- domain/ports/outline_errors.py: OutlineVolumeRefError（OutlineServiceError 子类，422 映射）
- domain/services/outline_service.py:
  * _validate_outline_hierarchy 扩展 volume_id 分支（level≠volume 且 volume_id 非空 → RefError；
    volume_id 非空且指向 Volume 不存在/跨项目（复用 chapter_repo.get_volume）→ RefError；
    同项目已有卷纲引用同一 Volume（repo.get_outline_by_volume 排除自身）→ RefError = 422）
  * create_outline 加 volume_id 参数（默认 None，向后兼容）
  * get_volume_outline(volume_id) 解析链 → 返回关联卷纲或 None
  * update_outline 透传 OutlineUpdate.volume_id（"" → None 清除）
- api/routers/outlines.py: OutlineCreateBody 加 volume_id 并透传（kwargs 形态 volume_id=...）；
  新增 GET /outlines/by-volume/{volume_id} 解析端点（无关联 → 404「卷纲不存在」）
- infrastructure/database/models/outline.py: OutlineORM 加 volume_id 列
  （Integer, FK volumes.id SET NULL, 已索引）+ 唯一索引 uq_outlines_volume_id
- infrastructure/database/repositories/outline_repo.py: 双向映射透传 volume_id；
  新增 get_outline_by_volume(volume_id, exclude_outline_id=None) -> Outline | None
- infrastructure/database/repositories/chapter_repo.py: delete_volume 显式
  UPDATE outlines SET volume_id=NULL WHERE volume_id=X（镜像 delete_chapter 清 chapter_id）
- core/database.py: ensure_outline_volume_id_column(conn) 迁移（加列 + 建唯一索引 +
  幂等 + 表不存在 no-op）；api/app.py 接线到 create_tables() 后

RED 预期形态（四层失败类别地图，规则 1q;整文件可收集，零收集 ERROR）:
- R1/R2 models 层: Outline/OutlineCreate/OutlineUpdate 无 volume_id 字段（extra='ignore'
  静默丢弃）→ model_dump()["volume_id"] KeyError
- R3-R6 service 层: create_outline 无 volume_id kwarg → TypeError
- R8 api 层: OutlineCreateBody 无 volume_id + create_outline mock 断言缺 kwarg →
  AssertionError；by-volume 端点不存在 → 404
- R7/R9 repo 层: Outline._volume_id 引用（_outline_domain_to_orm 访问 domain.volume_id）
  → AttributeError / ORM 无 volume_id 列 → FK 建表失败
- R10 database: ensure_outline_volume_id_column 缺失 → 用例体 lazy import ImportError

依据: specs/f56-volume-outline-link/spec.md §2/§3/§4/§5/§7/§8。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 缺失错误类 stub（置主 import 前，规则 1h）: RED 阶段 ImportError → 模块级 stub；
# GREEN 建真实类后 try import 命中，stub 分支不再执行。
try:
    from inkflow.domain.ports.outline_errors import OutlineVolumeRefError
except ImportError:  # RED 阶段: 新错误类未实现 → stub（GREEN 建真实类替换）

    class OutlineVolumeRefError(Exception):
        """卷关联引用错误 stub（GREEN 建真实类替换）."""


from inkflow.api.app import app
from inkflow.core.database import Base
from inkflow.domain.models.chapter import Volume
from inkflow.domain.models.outline import Outline, OutlineCreate, OutlineUpdate
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.services.outline_service import OutlineService
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.chapter_repo import SQLiteChapterRepository
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
    volume_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用大纲实体（固定时间戳；volume_id 透传——RED 阶段被 extra='ignore' 丢弃）."""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        level=level,
        parent_id=parent_id,
        chapter_id=chapter_id,
        volume_id=volume_id,
        created_at=TS,
        updated_at=TS,
    )


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合（R10 迁移断言用）."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 默认全方法可用（显式默认值，规则 1m）."""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    # 解析链 / 一双一校验用（GREEN 协议含该方法；RED 显式 AsyncMock 使断言可达）
    repo.get_outline_by_volume = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_chapter_repo() -> MagicMock:
    """Mock ChapterRepositoryProtocol — get_volume 用于 volume_id 存在性校验."""
    repo = MagicMock(spec=ChapterRepositoryProtocol)
    repo.get_chapter = AsyncMock(return_value=None)
    repo.get_volume = AsyncMock(return_value=None)
    return repo


def _make_service(repo: MagicMock, chapter_repo: MagicMock | None = None) -> OutlineService:
    """构造被测 OutlineService（全 Mock 注入；chapter_repo 可选扩展注入）."""
    if chapter_repo is None:
        return OutlineService(repository=repo)
    return OutlineService(repository=repo, chapter_repo=chapter_repo)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock OutlineService（镜像 test_outline_api.py 模式）."""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestVolumeUnifyModels:
    """R1/R2: models 层 volume_id 字段契约."""

    def test_r1_models_have_volume_id_field(self) -> None:
        """R1 models：Outline/OutlineCreate/OutlineUpdate 含 volume_id 字段（默认 None）.

        RED 预期: Pydantic extra='ignore' 静默丢字段 → model_dump() 无 volume_id 键 →
        KeyError（模型层失败形态）。
        GREEN 必实现: Outline/OutlineCreate volume_id: uuid.UUID | None = None；
        OutlineUpdate volume_id: uuid.UUID | str | None = None（"" 清除）。
        """
        outline = _outline("卷纲", level="volume")
        dumped = outline.model_dump()
        assert dumped["volume_id"] is None  # RED: KeyError

        create = OutlineCreate(project_id=PID, name="卷纲", level="volume")
        create_dump = create.model_dump()
        assert create_dump["volume_id"] is None  # RED: KeyError

        update = OutlineUpdate(name="改名")
        update_dump = update.model_dump()
        assert update_dump["volume_id"] is None  # RED: KeyError

    def test_r2_models_update_volume_id_clear_semantics(self) -> None:
        """R2 models：OutlineUpdate volume_id 显式 ""（清除）与 None（不修改）语义.

        GREEN 必实现: OutlineUpdate.volume_id: uuid.UUID | str | None = None；
        传入 "" / None 路径由 service 转 None 清除（对齐 chapter_id 先例）。
        """
        assert OutlineUpdate(name="x", volume_id="").volume_id == ""
        assert OutlineUpdate(name="x", volume_id=None).volume_id is None
        assert OutlineUpdate(name="x").model_fields_set == {"name"}


class TestVolumeUnifyService:
    """R3-R6: service 层 volume_id 校验 + 解析链契约（全 Mock repo 轨）."""

    @pytest.mark.asyncio
    async def test_r3_service_volume_id_on_non_volume_raises_ref_error(
        self, mock_repo, mock_chapter_repo
    ) -> None:
        """R3 service：level != volume 且 volume_id 非空 → OutlineVolumeRefError.

        RED 预期: create_outline 无 volume_id kwarg → TypeError（service 层失败形态）。
        GREEN 必实现: create_outline 加 volume_id 参数；level≠volume 且 volume_id 非空 →
        OutlineVolumeRefError（422，无需查库）。
        """
        svc = _make_service(mock_repo, mock_chapter_repo)
        with pytest.raises(OutlineVolumeRefError):
            await svc.create_outline(PID, "卷纲", level="overall", volume_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_r4_service_volume_id_unknown_volume_raises_ref_error(
        self, mock_repo, mock_chapter_repo
    ) -> None:
        """R4 service：volume_id 指向不存在/跨项目 Volume → OutlineVolumeRefError.

        RED 预期: create_outline 无 volume_id kwarg → TypeError（service 层失败形态）。
        GREEN 必实现: level=volume 且 volume_id 非空 → chapter_repo.get_volume(volume_id)
        为 None（不存在/跨项目）→ OutlineVolumeRefError（422）。
        """
        svc = _make_service(mock_repo, mock_chapter_repo)
        with pytest.raises(OutlineVolumeRefError):
            await svc.create_outline(PID, "卷纲", level="volume", volume_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_r5_service_duplicate_volume_outline_raises_ref_error(
        self, mock_repo, mock_chapter_repo
    ) -> None:
        """R5 service：一个 Volume 至多关联一个卷纲，重复关联 → OutlineVolumeRefError（422）.

        RED 预期: create_outline 无 volume_id kwarg → TypeError（service 层失败形态）。
        GREEN 必实现: repo.get_outline_by_volume(volume_id, exclude_outline_id=当前 id)
        已存在同卷卷纲 → OutlineVolumeRefError（"卷已关联卷纲"，422）。
        """
        vol_id = uuid.uuid4()
        existing = _outline("已有卷纲", level="volume", volume_id=vol_id)
        mock_repo.get_outline_by_volume = AsyncMock(return_value=existing)
        mock_chapter_repo.get_volume = AsyncMock(
            return_value=Volume(id=vol_id, project_id=PID, title="卷一", order_index=0.0)
        )
        svc = _make_service(mock_repo, mock_chapter_repo)
        with pytest.raises(OutlineVolumeRefError):
            await svc.create_outline(PID, "另一卷纲", level="volume", volume_id=vol_id)

    @pytest.mark.asyncio
    async def test_r6_service_volume_outline_without_volume_id_creates_ok(
        self, mock_repo
    ) -> None:
        """R6 service：卷纲未设 volume_id（暂不关联写作分组卷）→ 合法创建.

        RED 预期: create_outline 无 volume_id kwarg → TypeError（service 层失败形态）。
        GREEN 必实现: 未设 volume_id 的 level=volume 卷纲合法；repo.add 返回
        Outline 含 level=volume/volume_id=None。
        """
        saved = _outline("独立卷纲", level="volume")
        mock_repo.add = AsyncMock(return_value=saved)
        svc = _make_service(mock_repo)
        result = await svc.create_outline(PID, "独立卷纲", level="volume")
        assert result.model_dump()["level"] == "volume"
        assert result.model_dump()["volume_id"] is None

    @pytest.mark.asyncio
    async def test_r6b_service_resolution_chain_get_volume_outline(self, mock_repo) -> None:
        """R6b service：解析链 get_volume_outline(volume_id) → 关联卷纲或 None.

        RED 预期: OutlineService 无 get_volume_outline 方法 → AttributeError。
        GREEN 必实现: get_volume_outline 委托 repo.get_outline_by_volume(volume_id)，
        返回关联卷纲（level=volume）；无则 None（返空并提示）。
        """
        vol_id = uuid.uuid4()
        linked = _outline("卷纲", level="volume", volume_id=vol_id)
        mock_repo.get_outline_by_volume = AsyncMock(return_value=linked)
        svc = _make_service(mock_repo)
        got = await svc.get_volume_outline(vol_id)
        assert got is not None
        assert got.level == "volume"
        assert got.volume_id == vol_id

        mock_repo.get_outline_by_volume = AsyncMock(return_value=None)
        none = await svc.get_volume_outline(uuid.uuid4())
        assert none is None


class TestVolumeUnifyAPI:
    """R8: 大纲端点 volume_id 透传 + by-volume 解析端点（Mock Service 层）."""

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_r8_api_create_and_patch_passthrough_volume_id(
        self, mock_get_svc: MagicMock
    ) -> None:
        """R8 api：POST 透传 volume_id；PATCH 透传 "" 清除语义.

        RED 预期: ① POST 断言 create_outline 收到 volume_id kwarg → 当前 router 只传
        level/parent_id/chapter_id → AssertionError；② PATCH 断言 update_arg.volume_id
        == "" → OutlineUpdate 无 volume_id 字段 → AttributeError。
        GREEN 必实现: OutlineCreateBody 加 volume_id + create 调用以 kwargs 形态透传
        （volume_id=...）；PATCH 透传 OutlineUpdate（volume_id="" 由 service 转 None 清除）。
        """
        svc = _mock_svc(mock_get_svc)
        outline = _outline("卷纲", level="volume")
        svc.create_outline = AsyncMock(return_value=outline)
        svc.update_outline = AsyncMock(return_value=outline)

        vol_id = uuid.uuid4()
        response = client.post(
            f"/api/v1/projects/{PID}/outlines",
            json={"name": "卷纲", "level": "volume", "volume_id": str(vol_id)},
        )
        assert response.status_code == 201
        svc.create_outline.assert_awaited_once_with(
            PID, "卷纲", "", 0,
            level="volume",
            parent_id=None,
            chapter_id=None,
            volume_id=vol_id,
        )  # RED: AssertionError（router 未透传 volume_id）

        oid = uuid.uuid4()
        resp2 = client.patch(f"/api/v1/outlines/{oid}", json={"volume_id": ""})
        assert resp2.status_code == 200
        update_arg = svc.update_outline.call_args.args[1]
        assert update_arg.volume_id == ""  # RED: AttributeError（OutlineUpdate 无 volume_id 字段）
        assert "volume_id" in update_arg.model_fields_set

    @patch("inkflow.api.routers.outlines.get_outline_service")
    def test_r8b_api_resolution_by_volume_endpoint(self, mock_get_svc: MagicMock) -> None:
        """R8b api：GET /outlines/by-volume/{volume_id} 解析「当前卷 → 关联卷纲」.

        RED 预期: 端点未注册 → 404。
        GREEN 必实现: 新端点调用 svc.get_volume_outline(vid)；有 → 200 + Outline；
        无关联 → 404「卷纲不存在」。
        """
        svc = _mock_svc(mock_get_svc)
        vol_id = uuid.uuid4()
        linked = _outline("卷纲", level="volume", volume_id=vol_id)
        svc.get_volume_outline = AsyncMock(return_value=linked)

        resp = client.get(f"/api/v1/outlines/by-volume/{vol_id}")
        assert resp.status_code == 200  # RED: 端点不存在 → 404
        assert resp.json()["volume_id"] == str(vol_id)

        # 无关联 → 404
        svc.get_volume_outline = AsyncMock(return_value=None)
        resp2 = client.get(f"/api/v1/outlines/by-volume/{uuid.uuid4()}")
        assert resp2.status_code == 404


@pytest.mark.integration
class TestVolumeUnifyRepo:
    """R7/R9: Outline ORM ↔ 领域往返含 volume_id + delete_volume 联动（真实 in-memory SQLite）."""

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
        """一个基础项目（大纲/卷的 FK 依赖）."""
        p = ProjectORM(name="测试项目")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)
        return p

    async def test_r7_repo_roundtrip_with_volume_id(self, db_session, project):
        """R7 repo：Outline ORM ↔ 领域往返含 volume_id + get_outline_by_volume 解析.

        RED 预期: 领域 Outline 无 volume_id（extra='ignore' 丢弃）+ ORM 无对应列 →
        _outline_domain_to_orm 访问 domain.volume_id → AttributeError。
        GREEN 必实现: OutlineORM 加 volume_id 列 + repo 双向映射透传 +
        get_outline_by_volume 查询。
        """
        repo = SQLiteOutlineRepository(db_session)

        # 真实 Volume 行（volume_id FK 目标）
        vol_repo = SQLiteChapterRepository(db_session)
        vol = await vol_repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=project.id),
                title="卷一",
                order_index=0.0,
            )
        )

        parent = await repo.add(
            _outline(
                "整体大纲", project_id=uuid.UUID(int=project.id), level="overall"
            )
        )
        gang = await repo.add(
            _outline(
                "卷一纲",
                project_id=uuid.UUID(int=project.id),
                level="volume",
                parent_id=parent.id,
                volume_id=vol.id,
            )
        )

        got = await repo.get(gang.id.int)
        assert got is not None
        dumped = got.model_dump()
        assert dumped["volume_id"] == vol.id  # RED: KeyError / AttributeError
        assert dumped["level"] == "volume"

        resolved = await repo.get_outline_by_volume(vol.id.int)  # RED: AttributeError
        assert resolved is not None
        assert resolved.id == gang.id

    async def test_r9_repo_delete_volume_unlinks_outline(self, db_session, project):
        """R9 repo：删除 Volume → 其卷纲 volume_id 置 NULL（卷纲保留）.

        RED 预期: ORM 无 volume_id 列 → 建表/往返失败（前置于断言）。
        GREEN 必实现: chapter_repo.delete_volume 显式 UPDATE outlines SET volume_id=NULL
        WHERE volume_id=X；卷纲行保留、volume_id 变 None。
        """
        repo = SQLiteOutlineRepository(db_session)
        vol_repo = SQLiteChapterRepository(db_session)
        vol = await vol_repo.add_volume(
            Volume(
                id=uuid.uuid4(),
                project_id=uuid.UUID(int=project.id),
                title="卷一",
                order_index=0.0,
            )
        )
        gang = await repo.add(
            _outline(
                "卷一纲",
                project_id=uuid.UUID(int=project.id),
                level="volume",
                volume_id=vol.id,
            )
        )

        ok = await vol_repo.delete_volume(vol.id.int)
        assert ok is True

        still = await repo.get(gang.id.int)
        assert still is not None  # 卷纲保留
        assert still.model_dump()["volume_id"] is None  # 解绑


class TestVolumeUnifyDatabase:
    """R10: ensure_outline_volume_id_column 迁移契约（真 SQLite 同步轨）."""

    def test_r10_database_ensure_outline_volume_id_column_migration(self) -> None:
        """R10 database：ensure_outline_volume_id_column 迁移（加列+建索引+幂等+no-op）.

        RED 预期: inkflow.core.database 无 ensure_outline_volume_id_column → 用例体 lazy
        import → ImportError（FAILED 形态，非收集 ERROR，规则 1c 混合轨）。
        GREEN 必实现: ensure_outline_volume_id_column(conn)——PRAGMA table_info(outlines) →
        无 volume_id → ALTER ADD COLUMN volume_id INTEGER + CREATE UNIQUE INDEX IF NOT EXISTS
        uq_outlines_volume_id；表不存在（全新环境）→ no-op。
        """
        from inkflow.core.database import ensure_outline_volume_id_column  # RED: ImportError

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE outlines (id INTEGER PRIMARY KEY, project_id INTEGER, "
                    "name TEXT, description TEXT, sort_order INTEGER, level VARCHAR(16), "
                    "parent_id INTEGER, chapter_id INTEGER, extra JSON, "
                    "created_at DATETIME, updated_at DATETIME)"
                )
            )
            conn.commit()

            ensure_outline_volume_id_column(conn)
            conn.commit()
            cols = _cols(conn, "outlines")
            assert "volume_id" in cols
            idx = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='outlines'")
            ).fetchall()
            assert any(r[0] == "uq_outlines_volume_id" for r in idx)

            # 幂等：二次调用不抛错且列集合不变
            ensure_outline_volume_id_column(conn)
            conn.commit()
            assert _cols(conn, "outlines") == cols

        # 表不存在（全新环境）→ no-op 不抛错
        fresh = create_engine("sqlite:///:memory:")
        with fresh.connect() as conn:
            ensure_outline_volume_id_column(conn)
