"""S3f-T4 R1 契约：旧档脏行（损坏 JSON / 空串 / 纯空白）× 完整 lifespan + ORM 行级读（issue #869）。

依据 .hermes/plans/contract-s3f-t4.md §1 R1（D7 数据兼容，S3d #882 后补测面）：
既有 test_lenient_json.py 只模拟 LenientJSON result_processor（无真实行级读），
D1 迁移链测试只做 raw SQL PRAGMA/计数断言（未做 ORM SELECT 脏行/旧列行）。
本文件把两类空白钉为可执行断言：

R1-1 损坏 JSON × 启动 + ORM 读：旧档把 JSON 列写成空串/损坏文本（#261 修复前
  历史落库形态）→ 完整 lifespan（create_all + ensure 链 + seed）不抛 →
  ProjectRepository.get / CharacterRepository.list / WorldRepository.list /
  ExecutionStore.get_execution 逐字段断言 fallback 值（tags==[]、config==ProjectConfig()、
  extra=={}、stages==[]、hitl_payload is None），零异常。
  - projects.config='' / tags=''（空串 → fallback {} / []）
  - characters.extra='{损坏'（json.loads ValueError → fallback {}）
  - world_settings.extra='   '（纯空白 → fallback {}）
  - agent_executions.stages='[{"a":'（截断 JSON → fallback []）
  表形态：脏行表 = 与当前 ORM 全列对齐的旧版 DDL，但刻意缺「ensure 链会补的列」
  （projects 缺 active_watermark、characters 缺 brief、agent_executions 缺
  hitl_payload/relations/trace/thread_id）——链后 ALTER 补列 + NULL 新列 ×
  LenientJSON fallback 交互一并锁定（新增列对存量行全 NULL）。

R1-2 NULL 可空 JSON 列（可构造面）：agent.hitl_payload IS NULL（链补列后存量行
  天然全 NULL）→ 读 None→fallback None（并入 R1-1 断言行）。NOT NULL JSON 列写
  NULL 在 SQLite NOT NULL 约束下物理不可构造（父侧定稿「不造不可测需求」）；
  chat_messages conversation_id 回填（#858 族）由 D1 迁移链测试锁定
  （backend/tests/unit/test_database_migration_chain.py 断言 nulls==0）——本文件
  不重复，注释留痕。

R1-3 缺新列 × ORM 读（D1 增量：raw SQL 断言 → ORM SELECT）：旧 schema projects
  只建 id+name 两列 + 一行数据 → lifespan 链（create_all 只建缺表不补列，ensure_*
  全集无 projects config/tags/language/target_words/is_deleted/created_at/updated_at
  补列——仅 ensure_project_watermark_column 补 active_watermark）→ ORM SELECT 该行
  （SQLiteProjectRepository.get）→ 域对象 tags==[]、config==ProjectConfig()、
  language=='zh-CN'、target_words==0、active_watermark==0.0、name 保全。
  🔴 若当前实现缺补列 → OperationalError("no such column: projects.config/...") →
  RED = 真缺陷候选（contract §2：GREEN = 补 ensure_project_config_tags_columns），
  父侧裁定；若链已补齐 → 本用例转【G】回归锁定。

断言驱动 = repo/服务公开接口（禁私有方法）；每用例独立建库（tmp_path 文件 DB）。
镜像 backend/tests/unit/test_database_migration_chain.py 的 _migration_chain_env /
_run_lifespan（app.py from-import 独立绑定，engine/factory/data_dir 三处必换）。
"""

from __future__ import annotations

import contextlib
import importlib
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.config import config
from inkflow.domain.models.project import ProjectConfig
from inkflow.infrastructure.agent.execution_store import ExecutionStore
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository

app_module = importlib.import_module("inkflow.api.app")


# ── 旧库建造器（text() 真插 sqlite 文件，镜像 D1 builder 手法） ──


def _create_dirty_db(db: Path) -> None:
    """旧版脏库：projects/characters/world_settings 全列对齐当前 ORM（隔离列缺失
    变量，聚焦 LenientJSON 行级 fallback 语义），但刻意缺 ensure 链补列：
    projects 缺 active_watermark、characters 缺 brief、agent_executions 取
    #161/#270/#379/#338 前形态（缺 hitl_payload/relations/trace/thread_id）。

    行内容脏（空串/损坏 JSON/纯空白/截断 JSON）——历史手改库/旧版本落库形态。
    """
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE projects ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                "tags TEXT NOT NULL DEFAULT '', config TEXT NOT NULL DEFAULT '', "
                "language TEXT NOT NULL DEFAULT 'zh-CN', "
                "target_words INTEGER NOT NULL DEFAULT 0, "
                "is_deleted INTEGER NOT NULL DEFAULT 0, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, name, tags, config, created_at, updated_at) "
                "VALUES (1, '蜀山旧档', '', '', '2024-01-01 00:00:00', '2024-01-01 00:00:00')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, personality TEXT NOT NULL DEFAULT '', "
                "background TEXT NOT NULL DEFAULT '', goals TEXT NOT NULL DEFAULT '', "
                "extra TEXT NOT NULL DEFAULT '', "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO characters (id, project_id, name, personality, extra, "
                "created_at, updated_at) "
                "VALUES (1, 1, '玄明', '沉默寡言', '{损坏 json', "
                "'2024-01-01 00:00:00', '2024-01-01 00:00:00')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE world_settings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', "
                "content TEXT NOT NULL DEFAULT '', extra TEXT NOT NULL DEFAULT '', "
                "parent_id INTEGER, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO world_settings (id, project_id, name, category, content, "
                "extra, created_at, updated_at) "
                "VALUES (1, 1, '蜀山', 'geo', '蜀山主峰', '   ', "
                "'2024-01-01 00:00:00', '2024-01-01 00:00:00')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE agent_executions ("
                "id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, "
                "project_id TEXT NOT NULL, chapter_id TEXT, "
                "status TEXT NOT NULL DEFAULT 'completed', "
                "stages TEXT NOT NULL DEFAULT '[]', "
                "final_output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', "
                "total_duration_ms INTEGER NOT NULL DEFAULT 0, "
                "created_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agent_executions (id, pipeline, project_id, status, stages, "
                "created_at) "
                "VALUES ('exec-0001', 'builtin:write_chapter', "
                "'00000000-0000-0000-0000-000000000001', 'completed', '[{\"a\":', "
                "'2024-01-01 00:00:00')"
            )
        )
    engine.dispose()


def _create_minimal_projects_db(db: Path) -> None:
    """v0.11 形态旧库最小面：projects 只 id+name 两列 + 一行数据（D1 builder 同款）。

    R1-3 探针：当前 ensure_* 全集对 projects 只补 active_watermark，config/tags/
    language/target_words/is_deleted/created_at/updated_at 无任何补列——若 create_all
    只建缺表不补列，链后 ORM SELECT 该行即 OperationalError（真缺陷候选）。
    """
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        )
        conn.execute(text("INSERT INTO projects (id, name) VALUES (1, '蜀山')"))
    engine.dispose()


@contextlib.asynccontextmanager
async def _legacy_chain_env(tmp_path: Path, build):
    """建造旧库文件 + 重定向 lifespan 全局（engine/factory/data_dir），退出还原。

    ⚠️ 双换：``db_module.engine``（create_tables / run_character_group_members_migration
    运行时解析模块全局）与 ``app_module.engine`` / ``app_module.async_session_factory``
    （app.py from-import 独立绑定）。缺一则 lifespan 打到真实数据目录。
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
        yield engine
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
    """完整驱动一次 app lifespan（create_all + ensure 链 + seed + 优雅关闭 scheduler）。"""
    fake_app = SimpleNamespace(state=SimpleNamespace())
    async with app_module.lifespan(fake_app):
        pass


async def test_r1_dirty_json_rows_lifespan_then_orm_read_fallback(tmp_path: Path) -> None:
    """R1-1/R1-2：脏行（空串/损坏/纯空白/截断 JSON）× 完整 lifespan → ORM 读 fallback。

    lifespan 不抛（启动兼容）→ 真 ORM repo 读 → 域对象逐字段 fallback → 名称检索
    接口不抛。链同时把缺失列 ALTER 补上（存量行新列全 NULL → LenientJSON fallback
    / None 语义一并锁定）。
    """
    async with _legacy_chain_env(tmp_path, _create_dirty_db) as engine:
        await _run_lifespan(engine)  # 启动兼容：脏行 + 缺列旧库不得阻断迁移链

        async with db_module.async_session_factory() as session:
            # ① 损坏/空串 JSON 行 × ORM 读（ProjectRepository.get）
            project = await SQLiteProjectRepository(session).get(1)
            assert project is not None
            assert project.name == "蜀山旧档"  # 行保全
            assert project.tags == []  # tags='' → fallback []
            assert project.config == ProjectConfig()  # config='' → fallback {} → 默认配置
            assert project.language == "zh-CN"
            assert project.target_words == 0

            # ② characters.extra='{损坏 json'（ValueError → fallback {}）+ brief 补列后读
            characters, total = await SQLiteCharacterRepository(session).list(1)
            assert total == 1
            assert characters[0].name == "玄明"
            assert characters[0].extra == {}

            # ③ world_settings.extra='   '（纯空白 → fallback {}）
            worlds, ws_total = await SQLiteWorldRepository(session).list(1)
            assert ws_total == 1
            assert worlds[0].name == "蜀山"
            assert worlds[0].extra == {}

            # ④ agent_executions.stages='[{"a":'（截断 → fallback []）+ 链补
            #    hitl_payload 列存量行 NULL（R1-2：可空 JSON 列 NULL → fallback None）
            execution = await ExecutionStore(session).get_execution("exec-0001")
            assert execution is not None
            assert execution.status == "completed"
            assert execution.stages == []
            assert execution.hitl_payload is None

            # ⑤ 名称检索接口不抛（project 分页 list 面）
            projects, p_total = await SQLiteProjectRepository(session).list_all(limit=1)
            assert p_total == 1
            assert projects[0].name == "蜀山旧档"


async def test_r1_legacy_projects_minimal_columns_orm_read(tmp_path: Path) -> None:
    """R1-3：旧 schema projects(id,name)+行 → lifespan 链 → ORM SELECT 读行成功。

    契约（contract §1 R1-3 / §2）：链后 ProjectRepository.get 返回域对象，字段取
    ORM 默认（tags==[]、config 默认、language=='zh-CN'、target_words==0、
    active_watermark==0.0、name 保全）。
    🔴 RED 锚点：当前 ensure 链对 projects 无 config/tags/language/target_words/
    is_deleted/created_at/updated_at 补列（仅 active_watermark）——实现若未补 →
    OperationalError no such column → 本用例红 = 真缺陷候选，父侧裁定转 GREEN
    （补 ensure_project_config_tags_columns）；若已补 → 本用例【G】回归锁定。
    """
    async with _legacy_chain_env(tmp_path, _create_minimal_projects_db) as engine:
        await _run_lifespan(engine)

        async with db_module.async_session_factory() as session:
            project = await SQLiteProjectRepository(session).get(1)
            assert project is not None
            assert project.name == "蜀山"  # 存量行保全
            assert project.tags == []
            assert project.config == ProjectConfig()
            assert project.language == "zh-CN"
            assert project.target_words == 0
            assert project.active_watermark == 0.0
            assert project.is_deleted is False
