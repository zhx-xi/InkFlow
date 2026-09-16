"""#1156 契约：存量库遗留 ``projects.genre`` NOT NULL 列阻断项目创建（产品缺陷）。

现象（issue #1156）：
  本机在**真实数据目录**（`%APPDATA%\\InkFlow`，由旧版本一路迁移上来）跑
  ``e2e-writer-chat`` → 4 用例全红，断点在 ``createProjectViaUi()`` 末尾的
  ``expect(project-tree).toBeVisible()``；实际原因是「创建项目」返回 **HTTP 500**，
  对话框停在 ``创建失败: HTTP 500 标签 玄幻``。CI 绿是因为 CI 用全新隔离库。

实测根因（本目录 probe 留痕，见 issue #1156 诊断评论）：
  ``sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint
  failed: projects.genre``——当前 ORM ``ProjectORM`` 已无 ``genre`` 字段
  （#595「删 genre 枚举迁 tags」），INSERT 列清单不含 ``genre``；但存量库里
  ``genre`` 是**没有 SQL DEFAULT 的 NOT NULL 列**（历史 schema 遗留），
  于是每一次 INSERT 都被约束拒绝 → 500 → 项目建不出来 → ``project-tree`` 永不出现。

  全新库（``create_all`` 按当前 ORM 建表）**没有** ``genre`` 列 → 不受影响。
  这解释了「CI 绿 / 本机红」的差异，也说明这是**存量用户可复现的产品缺陷**
  （升级用户无法创建项目），E2E 只是恰好充当了 canary。

契约（本文件锁定，父侧口径）：
  C1 lifespan 兼容：带遗留 `genre NOT NULL` 列的存量库跑完整 ``app.lifespan``
     迁移链**不得抛异常**（当前实现抛 → RED）。
  C2 迁移后写入可用：迁移链跑完后，走公开仓储接口 ``SQLiteProjectRepository.add``
     创建项目**必须成功**（当前实现 IntegrityError → RED）。
  C3 数据保全：存量 ``projects`` 行**不被删除**，``name``/``tags``/``config`` 等
     既有字段值原样保留（防「重建表丢数据」回归）。
  C4 幂等：迁移链连跑两次（模拟重启）不抛、不重复动作。
  C5 反例守护（非回归）：全新库（无 ``genre`` 列）跑 lifespan 仍正常，且迁移
     助手对「表不存在 / 列已不存在」为 no-op（PRAGMA 守卫）——防把守卫写死。

断言驱动 = 公开接口（lifespan 上下文 + 仓储 add/get + raw SQL PRAGMA/计数），
禁私有方法。每用例独立建库（tmp_path 文件 DB）。harness 镜像
``test_legacy_dirty_data_compat.py`` 的 ``_legacy_chain_env`` / ``_run_lifespan``
（app.py from-import 独立绑定，engine/factory/data_dir 三处必换）。
"""

from __future__ import annotations

import contextlib
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.config import config
from inkflow.domain.services.project_service import ProjectService
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)

app_module = importlib.import_module("inkflow.api.app")


# ── 存量库建造器：projects 表带历史遗留 `genre NOT NULL`（无 DEFAULT） ──

# 与 #1156 实测的存量库 DDL 逐列对齐：genre VARCHAR(50) NOT NULL 且无 DEFAULT；
# active_watermark/tags 已由历史 ensure 链补上（带 DEFAULT），故此处不缺。
_LEGACY_PROJECTS_DDL = (
    "CREATE TABLE projects ("
    "id INTEGER NOT NULL, "
    "name VARCHAR(100) NOT NULL, "
    "genre VARCHAR(50) NOT NULL, "
    "language VARCHAR(10) NOT NULL, "
    "target_words INTEGER NOT NULL, "
    "config JSON NOT NULL, "
    "is_deleted BOOLEAN NOT NULL, "
    "created_at DATETIME NOT NULL, "
    "updated_at DATETIME NOT NULL, "
    "active_watermark FLOAT NOT NULL DEFAULT 0.0, "
    "tags JSON NOT NULL DEFAULT '[]', "
    "PRIMARY KEY (id))"
)


def _create_legacy_db_with_genre(db: Path) -> None:
    """存量库：projects 带遗留 ``genre NOT NULL``（无 DEFAULT）+ 一行既有数据。"""
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text(_LEGACY_PROJECTS_DDL))
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, name, genre, language, target_words, config, is_deleted, "
                "created_at, updated_at, tags) "
                "VALUES (1, '蜀山旧档', '仙侠', 'zh-CN', 1000000, '{}', 0, "
                "'2024-01-01 00:00:00', '2024-01-01 00:00:00', '[\"玄幻\"]')"
            )
        )
    engine.dispose()


def _create_empty_db(db: Path) -> None:
    """C5 反例：完全空库（无 projects 表）→ lifespan 应走 create_all 全新建表。"""
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
    engine.dispose()


@contextlib.asynccontextmanager
async def _legacy_chain_env(tmp_path: Path, build):
    """建造旧库文件 + 重定向 lifespan 全局（engine/factory/data_dir），退出还原。

    ⚠️ 双换：``db_module.engine``（create_tables / 迁移助手运行时解析模块全局）
    与 ``app_module.engine`` / ``app_module.async_session_factory``（app.py
    from-import 独立绑定）。缺一则 lifespan 打到真实数据目录。
    """
    db_file = tmp_path / "inkflow.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    build(db_file)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    event.listen(engine.sync_engine, "connect", db_module._set_sqlite_pragma)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    saved = (
        db_module.engine,
        db_module.async_session_factory,
        app_module.engine,
        app_module.async_session_factory,
        config.data_dir,
    )
    db_module.engine = engine
    db_module.async_session_factory = factory
    app_module.engine = engine
    app_module.async_session_factory = factory
    config.data_dir = data_dir
    try:
        yield engine, db_file
    finally:
        await engine.dispose()
        (
            db_module.engine,
            db_module.async_session_factory,
            app_module.engine,
            app_module.async_session_factory,
            config.data_dir,
        ) = saved


async def _run_lifespan(engine) -> None:
    """完整驱动一次 app lifespan（create_all + ensure 链 + seed + 优雅关闭）。"""
    fake_app = SimpleNamespace(state=SimpleNamespace())
    async with app_module.lifespan(fake_app):
        pass


def _project_columns(db_file: Path) -> set[str]:
    """raw SQL 读 projects 列名（独立连接，绕 ORM 缓存）。"""
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        return {row[1] for row in rows}
    finally:
        engine.dispose()


# ── C1：lifespan 兼容（遗留 genre NOT NULL 不得阻断迁移链） ──


async def test_c1_legacy_genre_lifespan_does_not_raise(tmp_path: Path) -> None:
    """C1：带遗留 ``genre NOT NULL`` 的存量库跑完整 lifespan 不抛。

    🔴 RED 锚点：当前 lifespan 无任何针对遗留 ``genre`` 列的处理，链本身也不抛
    （抛点发生在 INSERT 写入时，即 C2）——故 C1 当前即应 PASS，作为**回归锁定**
    （防修复引入「迁移链自己崩」）。真正 RED 在 C2。
    """
    async with _legacy_chain_env(tmp_path, _create_legacy_db_with_genre) as (engine, _db):
        await _run_lifespan(engine)  # 不得抛


# ── C2：迁移后写入可用（核心 RED） ──


async def test_c2_create_project_after_legacy_migration_succeeds(tmp_path: Path) -> None:
    """C2（核心 RED）：迁移链跑完后经公开服务创建项目必须成功。

    当前实现：存量库 ``genre`` 为无 DEFAULT 的 NOT NULL 列，而 ORM 不再写该列
    → ``IntegrityError: NOT NULL constraint failed: projects.genre``。
    """
    async with _legacy_chain_env(tmp_path, _create_legacy_db_with_genre) as (engine, _db):
        await _run_lifespan(engine)

        async with db_module.async_session_factory() as session:
            service = ProjectService(session)
            created = await service.create_project(
                name="E2E-新书",
                tags=["玄幻"],
                language="zh-CN",
                target_words=800000,
            )
            assert created.name == "E2E-新书"
            assert created.tags == ["玄幻"]

            read_back = await SQLiteProjectRepository(session).get(created.id.int)
            assert read_back is not None
            assert read_back.name == "E2E-新书"


# ── C3：存量数据保全 ──


async def test_c3_legacy_rows_preserved_after_migration(tmp_path: Path) -> None:
    """C3：迁移后存量 projects 行不被删除，既有字段值原样保留。"""
    async with _legacy_chain_env(tmp_path, _create_legacy_db_with_genre) as (engine, _db):
        await _run_lifespan(engine)

        async with db_module.async_session_factory() as session:
            repo = SQLiteProjectRepository(session)
            legacy = await repo.get(1)
            assert legacy is not None, "存量行被删（数据丢失回归）"
            assert legacy.name == "蜀山旧档"
            assert legacy.tags == ["玄幻"]
            assert legacy.language == "zh-CN"
            assert legacy.target_words == 1000000

            _projects, total = await repo.list_all(limit=10)
            assert total >= 1


# ── C4：幂等（重启重跑不抛、不重复动作） ──


async def test_c4_migration_idempotent_across_restart(tmp_path: Path) -> None:
    """C4：同一存量库连跑两次 lifespan（模拟重启）不抛，且写入仍可用。"""
    async with _legacy_chain_env(tmp_path, _create_legacy_db_with_genre) as (engine, _db):
        await _run_lifespan(engine)
        await _run_lifespan(engine)  # 第二次：迁移助手须为 no-op（PRAGMA 守卫）

        async with db_module.async_session_factory() as session:
            service = ProjectService(session)
            created = await service.create_project(
                name="重启后新书", tags=["仙侠"], language="zh-CN"
            )
            assert (await SQLiteProjectRepository(session).get(created.id.int)) is not None


# ── C5：反例守护（全新库不受影响 + 列已不存在时 no-op） ──


async def test_c5_fresh_db_unaffected_and_helper_is_noop(tmp_path: Path) -> None:
    """C5：全新空库跑 lifespan 正常建表 + 写入成功（修复不得破坏全新安装路径）。"""
    async with _legacy_chain_env(tmp_path, _create_empty_db) as (engine, db_file):
        await _run_lifespan(engine)

        # 全新库按当前 ORM 建表 → 本就不该有 genre 列
        assert "genre" not in _project_columns(db_file)

        async with db_module.async_session_factory() as session:
            service = ProjectService(session)
            created = await service.create_project(
                name="全新库新书", tags=["都市"], language="zh-CN"
            )
            # 域 id 为 UUID(int=orm.id)（见 _orm_to_domain）→ 反解回 int 主键查回
            assert (await SQLiteProjectRepository(session).get(created.id.int)) is not None


# ── C2b：遗留库经修复后不得再残留 genre 列（迁移真实生效，非「绕过写入」） ──


async def test_c2b_legacy_genre_column_removed_after_migration(tmp_path: Path) -> None:
    """C2b：迁移后存量库 ``genre`` 列必须已消失（证明迁移真执行）。

    判据来源：issue #1156 修复方向 = 把遗留无 DEFAULT 的 NOT NULL 列从存量库摘除
    （对齐既有 ``ensure_world_drop_is_deleted`` 的 ``DROP COLUMN`` 先例）。
    ⚠️ 若最终实现改为「INSERT 时显式补写 genre」而非摘列，本用例需同步调整
    （父侧裁定）；当前按「摘列」锁定，因为它同时消除写入约束与死列。
    """
    async with _legacy_chain_env(tmp_path, _create_legacy_db_with_genre) as (engine, db_file):
        await _run_lifespan(engine)
        assert "genre" not in _project_columns(db_file), (
            "遗留 genre 列未被摘除（迁移未生效——写入成功可能只是绕过了约束）"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
