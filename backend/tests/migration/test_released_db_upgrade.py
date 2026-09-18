"""#1005 真实发布版 DB 迁移升级回归 — snapshot fixture 驱动的全链升级验证.

与 test_database_migration_chain.py（合成旧库）互补：本文件用**已合入正式版的
真实落盘 DB**（v0.14.0 起，每个正式版归档一份于 fixtures/<version>/）验证
「旧库 → 最新代码 lifespan 全链 → 语义可用」：

- M1 fixture 完整性: sha256 对账 MANIFEST（防仓库内二进制被意外改写）
- M2 升级无错: lifespan 全链（create_all + ensure_* + FK 重建 + seed）零异常
- M3 数据保全: 业务表行数按 MANIFEST 对账；关系表按当前 ORM 形态条件断言
  （#495 前: character_relations 保留；#495 后: 表消失 + 行迁入
  knowledge_relations 的 character↔character 子空间——断言随 ORM 真值源自动
  切换，两态都锁「关系数据不丢」）
- M4 语义可用: repo 层真实 CRUD（读项目/角色/章节 + 写更新 + 建删角色）
- M5 缺列自动补全: 当前 ORM 全部表 SELECT 探针（旧库缺列 → OperationalError 即红）
- M6 FK 完好 + integrity_check + 重启幂等（lifespan 第二遍，行数不变）

fixture 演进约定（#1005 拍板遗留项，本文件定稿）:
- 每个新正式版发布后，用该 tag 代码生成 fixture 检入 fixtures/<version>/
  （生成器脚本 backend/tests/migration/fixtures/README.md）；
- MANIFEST.json = {version, sha256, size_bytes, tables: {表: 行数}, journal_mode}；
- 本测试对 fixtures/ 下全部版本参数化——旧版本 fixture 永久保留（升级路径
  跨多版本回归），不随版本演进而删除。

依据: issue #1005 · ADR-054（迁移体系现状）· 用户 2026-08-12「数据升级兼容测试」拍板。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.config import config
from inkflow.core.database import Base

app_module = importlib.import_module("inkflow.api.app")

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _discover_fixtures() -> list[Path]:
    """发现全部版本 fixture 目录（含 MANIFEST.json + inkflow.db）."""
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(
        d
        for d in FIXTURE_ROOT.iterdir()
        if d.is_dir() and (d / "MANIFEST.json").exists() and (d / "inkflow.db").exists()
    )


FIXTURES = _discover_fixtures()


def _load_manifest(fixture_dir: Path) -> dict:
    """读 fixture MANIFEST.json."""
    return json.loads((fixture_dir / "MANIFEST.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    """文件 sha256（分块读，fixture 可能 >1MB）."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 升级 harness（镜像 test_database_migration_chain._migration_chain_env 双换）──


class _UpgradeEnv:
    """把 lifespan 全局（engine/factory/data_dir）重定向到 fixture 副本 + 隔离目录."""

    def __init__(self, fixture_dir: Path, tmp_path: Path) -> None:
        self.manifest = _load_manifest(fixture_dir)
        self.db_file = tmp_path / "inkflow.db"
        shutil.copy2(fixture_dir / "inkflow.db", self.db_file)
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}")
        event.listen(self.engine.sync_engine, "connect", db_module._set_sqlite_pragma)
        self.factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self._saved: tuple | None = None

    async def __aenter__(self) -> _UpgradeEnv:
        self._saved = (
            db_module.engine,
            db_module.async_session_factory,
            app_module.engine,
            app_module.async_session_factory,
            config.data_dir,
        )
        db_module.engine = self.engine
        db_module.async_session_factory = self.factory
        app_module.engine = self.engine
        app_module.async_session_factory = self.factory
        config.data_dir = self.data_dir
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.engine.dispose()
        assert self._saved is not None
        (
            db_module.engine,
            db_module.async_session_factory,
            app_module.engine,
            app_module.async_session_factory,
            config.data_dir,
        ) = self._saved

    async def run_lifespan(self) -> None:
        """完整驱动一次 app lifespan（迁移链 + seed + scheduler 启停）."""
        fake_app = SimpleNamespace(state=SimpleNamespace())
        async with app_module.lifespan(fake_app):
            pass

    async def scalar(self, sql: str) -> int:
        """单值查询（行数对账用）."""
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(sql))).fetchone()
        assert row is not None
        return int(row[0])

    async def tables(self) -> set[str]:
        """当前库全部表名."""
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            ).fetchall()
        return {r[0] for r in rows}


pytestmark = pytest.mark.skipif(
    not FIXTURES, reason="无发布版 fixture（fixtures/<version>/ 未检入）"
)


@pytest.fixture(params=FIXTURES, ids=lambda d: d.name)
def fixture_dir(request: pytest.FixtureRequest) -> Path:
    """参数化：每个已检入的发布版 fixture 目录."""
    return request.param  # type: ignore[no-any-return]


async def test_m1_fixture_integrity(fixture_dir: Path) -> None:
    """M1: fixture 二进制与 MANIFEST sha256 对账（防意外改写/损坏）."""
    manifest = _load_manifest(fixture_dir)
    db = fixture_dir / "inkflow.db"
    assert _sha256(db) == manifest["sha256"], (
        f"fixture {fixture_dir.name}/inkflow.db 与 MANIFEST sha256 不符——"
        "二进制被改写或损坏；重新生成 fixture 并更新 MANIFEST"
    )
    assert db.stat().st_size == manifest["size_bytes"]
    assert manifest["journal_mode"] == "delete", "fixture 必须是单文件 DB（无 WAL）"
    assert not (fixture_dir / "inkflow.db-wal").exists()
    assert not (fixture_dir / "inkflow.db-shm").exists()


async def test_m2_m6_full_upgrade(fixture_dir: Path, tmp_path: Path) -> None:
    """M2-M6: 旧库 → lifespan 全链 → 数据保全/语义可用/缺列补全/FK/重启幂等."""
    async with _UpgradeEnv(fixture_dir, tmp_path) as env:
        manifest = env.manifest
        expected = manifest["tables"]

        # ── M2 升级无错（第一遍 lifespan）──
        await env.run_lifespan()

        # ── M3 数据保全 ──
        # 业务核心表：行数与发布版落盘时一致
        for table in (
            "projects",
            "characters",
            "volumes",
            "chapters",
            "outlines",
            "world_settings",
            "timeline_events",
            "foreshadowings",
            "character_group_members",
        ):
            if table in expected:
                assert await env.scalar(f"SELECT COUNT(*) FROM {table}") == expected[table], (
                    f"{table} 行数漂移：升级迁移破坏存量数据"
                )

        # 关系表条件断言（#495 数据面统一前后两态都锁「关系数据不丢」）
        cr_in_orm = "character_relations" in Base.metadata.tables
        cr_expected = expected.get("character_relations", 0)
        if cr_in_orm:
            # #495 前：character_relations 仍是真值源，行原样保留
            assert await env.scalar("SELECT COUNT(*) FROM character_relations") == cr_expected
        else:
            # #495 后：表已并入 knowledge_relations（character↔character 子空间）
            live_tables = await env.tables()
            assert "character_relations" not in live_tables, "表应已随迁移 DROP"
            migrated = await env.scalar(
                "SELECT COUNT(*) FROM knowledge_relations "
                "WHERE source_type='character' AND target_type='character'"
            )
            assert migrated >= cr_expected, (
                f"character_relations {cr_expected} 行应全部迁入 knowledge_relations，"
                f"实际 character↔character 行 {migrated}"
            )

        # seed 面：builtin provider/agent 在新代码下仍幂等可用
        assert await env.scalar("SELECT COUNT(*) FROM provider_configs") >= 1
        assert await env.scalar("SELECT COUNT(*) FROM agents") >= 1

        # ── M5 缺列自动补全（当前 ORM 全部表 SELECT 探针）──
        # 旧库缺列 → no such column OperationalError 即红（ensure_* 漏接线的运行时面）
        async with env.engine.connect() as conn:
            for table_name, table in Base.metadata.tables.items():
                cols = ", ".join(f'"{c.name}"' for c in table.columns)
                await conn.execute(text(f'SELECT {cols} FROM "{table_name}" LIMIT 1'))

        # ── M6a FK 完好 + integrity ──
        async with env.engine.connect() as conn:
            violations = (await conn.execute(text("PRAGMA foreign_key_check"))).fetchall()
            assert violations == [], f"FK 违例: {violations[:3]}"
            integrity = (await conn.execute(text("PRAGMA integrity_check"))).fetchone()
            assert integrity is not None and integrity[0] == "ok"

        # ── M4 语义可用（repo 层真实 CRUD，非仅 schema 断言）──
        from inkflow.domain.models.character import Character
        from inkflow.infrastructure.database.repositories.chapter_repo import (
            SQLiteChapterRepository,
        )
        from inkflow.infrastructure.database.repositories.character_repo import (
            SQLiteCharacterRepository,
        )
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        async with env.factory() as session:
            project_repo = SQLiteProjectRepository(session)
            character_repo = SQLiteCharacterRepository(session)
            chapter_repo = SQLiteChapterRepository(session)

            # 读：项目分页 + 跨项目隔离验证（list_all 默认 updated_at DESC，
            # 项目选取不依赖排序——遍历找 fixture 规划的「蜀山」项目A）
            project_items, project_total = await project_repo.list_all()
            assert project_total >= 2 and len(project_items) >= 2, (
                "升级后项目不可读（应≥2，含隔离项目B）"
            )
            names = {p.name for p in project_items}
            assert "蜀山，我是掌门" in names and "测试项目B" in names, f"项目名漂移: {names}"
            project = next(p for p in project_items if p.name == "蜀山，我是掌门")
            pid = project.id
            project_b = next(p for p in project_items if p.name == "测试项目B")

            char_items, char_total = await character_repo.list(pid)
            assert char_total == 3 and len(char_items) == 3, "升级后角色不可读（项目A 应 3 角色）"
            # 跨项目隔离：项目B 的角色不串入项目A（1 角色），项目A 角色不串入 B
            b_chars, b_total = await character_repo.list(project_b.id)
            assert b_total == 1 and len(b_chars) == 1, "跨项目角色隔离破坏"

            chapter_items, chapter_total = await chapter_repo.list_chapters(pid)
            assert chapter_total == 3 and len(chapter_items) == 3, (
                "升级后章节不可读（项目A 应 3 章）"
            )
            first_chapter = chapter_items[0]
            assert first_chapter.content, "章节正文丢失"
            titles = {c.title for c in chapter_items}
            assert any("替师出诊" in t for t in titles), f"章节标题集漂移: {titles}"
            # 项目B 无章节（隔离）
            _, b_chapter_total = await chapter_repo.list_chapters(project_b.id)
            assert b_chapter_total == 0, "跨项目章节隔离破坏"

            # 写：章节内容更新往返（update_chapter 全字段覆盖）
            updated = first_chapter.model_copy(
                update={"content": first_chapter.content + "\n升级回归探针追加段。"}
            )
            await chapter_repo.update_chapter(updated)
            reread = await chapter_repo.get_chapter(updated.id)
            assert reread is not None
            assert "升级回归探针追加段" in reread.content, "升级后章节不可写"

            # 建+删：角色生命周期（含关系面清理路径不炸）
            import uuid as uuid_mod
            from datetime import UTC, datetime

            now = datetime.now(UTC)
            probe_char = Character(
                id=uuid_mod.uuid4(),
                project_id=project.id,
                name="升级探针角色",
                created_at=now,
                updated_at=now,
            )
            created = await character_repo.add(probe_char)
            assert await character_repo.hard_delete(created.id) is True

        # ── M6b 重启幂等（第二遍 lifespan，行数不变、无异常）──
        before = {
            t: await env.scalar(f"SELECT COUNT(*) FROM {t}")
            for t in ("projects", "characters", "chapters")
        }
        await env.run_lifespan()
        after = {
            t: await env.scalar(f"SELECT COUNT(*) FROM {t}")
            for t in ("projects", "characters", "chapters")
        }
        assert before == after, "重启后行数漂移（迁移不幂等）"
