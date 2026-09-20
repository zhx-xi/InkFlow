"""#1319-b 真实仓储穿透契约：_assemble_setting_context 必须能用真实 repo 工作。

背景（父侧实测，阻断级）：
`_assemble_setting_context`（agent_service.py:790）算 `project_int = uuid.UUID(project_id).int`，
并把该 **裸 int** 传给三源 `repo.list()`。但 ADR-060 D9 之后 repo 层
`require_uuid_pk`（_id_guard.py:17-46）**拒绝裸 int**（`raise TypeError`）：
- character_repo.py:227 `pid = require_uuid_pk(project_id)`
- world_repo.py:178   `pid = require_uuid_pk(project_id)`
- outline_repo.py:216 `pid = require_uuid_pk(project_id)`

后果：三源各自抛 TypeError → 被单源 except 吞掉 → `variables["setting"]` **永不写入**。
即 agent 轨（GUI 写作真实链路）的设定注入**从来没工作过**，而 mock 测试因
`MockCharacterRepo.list(self, project_id, *args, **kwargs)` 吸收任何入参而全绿。

本文件 = **真实 SQLite + 真实仓储**穿透契约（不用 mock repo），
是上述缺陷的复现与回归锁。

RED 预期（首轮）：
- test_setting_injected_with_real_repos: FAILED（setting 键不存在）
- test_override_filters_real_rows: FAILED
守护用例（首轮即 PASS）：
- test_repo_list_rejects_bare_int（锁 ADR-060 D9 契约不被绕过）

⚠️ ORM 主键用小的确定性 int（uuid4().int 溢 SQLite INT64）；
domain 侧 UUID 由 uuid.UUID(int=n) 映射（仓库惯例）。
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from inkflow.core.database import Base  # sys.path 注入后才可导入
from inkflow.domain.models.context import ContextOverride  # sys.path 注入后才可导入
from inkflow.domain.models.project import (  # sys.path 注入后才可导入
    Project,
    ProjectConfig,
)
from inkflow.domain.services.agent_service import (
    AgentService,  # sys.path 注入后才可导入
)
from inkflow.infrastructure.database.models.character import (
    CharacterORM,  # sys.path 注入后才可导入
)
from inkflow.infrastructure.database.models.project import (
    ProjectORM,  # sys.path 注入后才可导入
)
from inkflow.infrastructure.database.models.world import (
    WorldSettingORM,  # sys.path 注入后才可导入
)
from inkflow.infrastructure.database.repositories.character_repo import (  # sys.path 注入后才可导入
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import (  # sys.path 注入后才可导入
    SQLiteWorldRepository,
)

pytestmark = pytest.mark.asyncio

PID = 900001
CHAR_A, CHAR_B = 900011, 900012
WORLD_A, WORLD_B = 900021, 900022


def _u(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


class _StubStore:
    async def create_execution(self, *a: object, **k: object):
        raise AssertionError("本契约不跑管线")

    async def get_execution(self, *a: object, **k: object):
        return None

    async def update_status(self, *a: object, **k: object) -> None:
        return None

    async def update_stages(self, *a: object, **k: object) -> None:
        return None


class _ProjRepo:
    def __init__(self, project: Project | None) -> None:
        self.project = project

    async def get(self, _pid: object) -> Project | None:
        return self.project


@pytest.fixture
async def real_env():
    """真实 SQLite + 真实仓储 + 预置 2 角色 / 2 世界观（乙挂甲下，根条目唯一约束）。"""
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async with sf() as s:
        s.add(
            ProjectORM(
                id=PID, name="P", tags=["玄幻"], language="zh-CN", target_words=1000, config={}
            )
        )
        s.add(
            CharacterORM(
                id=CHAR_A,
                project_id=PID,
                name="角色甲",
                personality="甲的性格",
                background="",
                goals="",
            )
        )
        s.add(
            CharacterORM(
                id=CHAR_B,
                project_id=PID,
                name="角色乙",
                personality="乙的性格",
                background="",
                goals="",
            )
        )
        s.add(
            WorldSettingORM(
                id=WORLD_A, project_id=PID, name="世界观甲", category="设定", content="甲的内容"
            )
        )
        s.add(
            WorldSettingORM(
                id=WORLD_B,
                project_id=PID,
                parent_id=WORLD_A,
                name="世界观乙",
                category="设定",
                content="乙的内容",
            )
        )
        await s.commit()

    project = Project(
        id=_u(PID),
        name="P",
        tags=["玄幻"],
        language="zh-CN",
        target_words=1000,
        config=ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    yield sf, project
    await engine.dispose()


def _svc(session, project: Project) -> AgentService:
    return AgentService(
        pipeline=None,  # type: ignore[arg-type]  # 本契约不跑管线
        db_session=session,
        store=_StubStore(),
        project_repo=_ProjRepo(project),
        character_repo=SQLiteCharacterRepository(session),
        world_repo=SQLiteWorldRepository(session),
        outline_repo=None,
    )


class TestRealRepoGuard:
    async def test_repo_list_rejects_bare_int(self, real_env):
        """守护：真实 repo.list 拒绝裸 int（ADR-060 D9）——不得为兼容而放宽。

        首轮即 PASS，锁住「不许把 require_uuid_pk 改回接受 int」这条退路。
        """
        sf, _project = real_env
        async with sf() as s:
            with pytest.raises(TypeError, match="require_uuid_pk"):
                await SQLiteCharacterRepository(s).list(PID, limit=50)

    async def test_repo_list_accepts_uuid(self, real_env):
        """守护：真实 repo.list 接受 uuid.UUID 并返回真实行。

        首轮即 PASS，证明「传 UUID」是可行解。
        """
        sf, _project = real_env
        async with sf() as s:
            rows, total = await SQLiteCharacterRepository(s).list(_u(PID), limit=50)
        assert {c.name for c in rows} == {"角色甲", "角色乙"}
        assert total == 2


class TestSettingInjectionWithRealRepos:
    async def test_setting_injected_with_real_repos(self, real_env):
        """真实仓储下 setting 必须被注入（含全部角色与世界观）。

        RED 预期：FAILED（三源列表入参为裸 int → TypeError 被吞 → setting 缺键）。
        """
        sf, project = real_env
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {})

        assert "setting" in result, "真实仓储下 setting 必须注入（当前三源全抛 TypeError）"
        assert "角色甲" in result["setting"]
        assert "角色乙" in result["setting"]
        assert "世界观甲" in result["setting"]
        assert "世界观乙" in result["setting"]

    async def test_override_filters_real_rows(self, real_env):
        """真实仓储下 override 白名单必须真正过滤到行。

        RED 预期：FAILED（同因，setting 缺键）。
        """
        sf, project = real_env
        override = ContextOverride(character_ids=[_u(CHAR_A)], world_ids=[_u(WORLD_A)])
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, override)

        assert "setting" in result
        assert "角色甲" in result["setting"]
        assert "角色乙" not in result["setting"]
        assert "世界观甲" in result["setting"]
        assert "世界观乙" not in result["setting"]

    async def test_override_empty_removes_source_real(self, real_env):
        """真实仓储下显式空列表 = 该源删空，未覆盖源保持全注入。

        RED 预期：FAILED（同因）。
        """
        sf, project = real_env
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(
                str(project.id), {}, ContextOverride(character_ids=[])
            )

        assert "setting" in result
        assert "角色甲" not in result["setting"]
        assert "角色乙" not in result["setting"]
        assert "世界观甲" in result["setting"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "--no-header"]))
