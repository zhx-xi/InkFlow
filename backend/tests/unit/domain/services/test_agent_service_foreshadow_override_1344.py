"""#1344 真实仓储穿透契约：_assemble_setting_context 必须消费 foreshadowing_ids。

## 背景（父侧实证）

`_assemble_setting_context`（agent_service.py:774-833，本契约所在分支基线）只装配
**角色/世界观/大纲三源**，白名单过滤仅落在 character_ids（:800-802）与 world_ids
（:813-815）。`ForeshadowingRepositoryProtocol` 已存在且 `ForeshadowingSource`
（sources.py:249-285）已用 `list_open` 产出 F6 注入集合，但 **agent 轨的设定装配完全
没有伏笔源** → `ContextOverride.foreshadowing_ids` 收到也无处作用。

对照：assemble 预览路径 `_apply_override`（context_service.py:333-367）**三源都实现**
（含 FORESHADOWING，:361-363）→ **两条路径能力不对齐**（issue #1344 明确点名）。

## 本契约锁什么

1. 伏笔源已装配：无 override 时 setting 含全部 open 伏笔（已回收的不注入）
2. 三态：None → 全量 / 显式 [] → 该源零产出 / 非空 → 仅白名单命中
3. **两路径对拍**：同一 override 下，_assemble_setting_context 的白名单集合
   与 _apply_override 对 ForeshadowingSource 产出的过滤结果**一致**
4. 可证伪自证：删掉伏笔源的白名单过滤 → 用例 2/3 必 FAIL

⚠️ ORM 主键用小的确定性 int（uuid4().int 溢 SQLite INT64）；domain UUID 由 uuid.UUID(int=n) 映射。
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.context import (
    ContextOverride,
    ContextSourceType,
)
from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingStatus,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.agent_service import AgentService
from inkflow.domain.services.context_service import _apply_override
from inkflow.infrastructure.context.sources import ForeshadowingSource
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)

pytestmark = pytest.mark.asyncio

PID = 901001
FS_A, FS_B, FS_RESOLVED = 901011, 901012, 901013


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
    """真实 SQLite + 真实伏笔仓储 + 预置 2 open 伏笔 + 1 resolved 伏笔。"""
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
            ForeshadowingORM(
                id=FS_A,
                project_id=PID,
                title="伏笔甲",
                description="甲的详情",
                priority=80,
                status="open",
                location="",
            )
        )
        s.add(
            ForeshadowingORM(
                id=FS_B,
                project_id=PID,
                title="伏笔乙",
                description="乙的详情",
                priority=60,
                status="open",
                location="",
            )
        )
        s.add(
            ForeshadowingORM(
                id=FS_RESOLVED,
                project_id=PID,
                title="已回收伏笔",
                description="不该注入",
                priority=90,
                status="resolved",
                location="",
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
        foreshadowing_repo=SQLiteForeshadowingRepository(session),
    )


class TestForeshadowingOverride:
    async def test_foreshadowing_source_assembled(self, real_env):
        """① 伏笔源已装配：无 override → setting 含全部 open 伏笔，不含已回收。

        RED 预期：FAILED（当前无伏笔源 → 伏笔条目永不出现）。
        """
        sf, project = real_env
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {})

        assert "setting" in result, "有 open 伏笔时 setting 必须注入"
        assert "伏笔甲" in result["setting"]
        assert "伏笔乙" in result["setting"]
        assert "已回收伏笔" not in result["setting"], "已回收伏笔不得注入（F6 注入集合 = open）"

    async def test_override_none_is_full(self, real_env):
        """② 三态 · None：显式传 None = 全量（含全部 open 伏笔）。"""
        sf, project = real_env
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, None)

        assert "setting" in result
        assert "伏笔甲" in result["setting"]
        assert "伏笔乙" in result["setting"]

    async def test_override_nonempty_filters(self, real_env):
        """③ 三态 · 非空：仅白名单命中的伏笔注入。

        RED 预期：FAILED（伏笔源缺失 / 未消费 foreshadowing_ids）。
        """
        sf, project = real_env
        override = ContextOverride(foreshadowing_ids=[_u(FS_A)])
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, override)

        assert "setting" in result
        assert "伏笔甲" in result["setting"]
        assert "伏笔乙" not in result["setting"]

    async def test_override_empty_removes_source(self, real_env):
        """④ 三态 · 显式 []：伏笔源零产出。

        RED 预期：FAILED（同因）。
        """
        sf, project = real_env
        override = ContextOverride(foreshadowing_ids=[])
        async with sf() as s:
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, override)

        assert "伏笔甲" not in result.get("setting", "")
        assert "伏笔乙" not in result.get("setting", "")


class TestTwoPathParity:
    async def test_parity_with_apply_override(self, real_env):
        """⑤ 两路径对拍：同一 override 下两条路径的伏笔集合一致。

        assemble 路径（_assemble_setting_context）与预览路径（_apply_override
        对 ForeshadowingSource.collect 产出）必须选出同一批伏笔。

        RED 预期：FAILED（assemble 路径无伏笔源 → 该侧集合为空）。
        """
        sf, project = real_env
        override = ContextOverride(foreshadowing_ids=[_u(FS_A)])

        async with sf() as s:
            repo = SQLiteForeshadowingRepository(s)
            # 预览路径：真实源产出 → _apply_override 过滤
            items = await ForeshadowingSource(repo).collect(project.id, None)
            preview = {
                item.metadata["foreshadowing_id"]
                for item in _apply_override(items, ContextSourceType.FORESHADOWING, override)
            }
            # agent 路径：真实装配
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, override)

        setting = result.get("setting", "")
        agent_ids = {str(_u(FS_A)) for _ in [1] if "伏笔甲" in setting} | {
            str(_u(FS_B)) for _ in [1] if "伏笔乙" in setting
        }

        assert preview == {str(_u(FS_A))}, "预览路径应只保留甲（对拍基准）"
        assert agent_ids == preview, f"两路径伏笔集合必须一致：预览={preview} agent={agent_ids}"

    async def test_parity_empty_override(self, real_env):
        """⑤b 两路径对拍 · 显式空：两侧都零产出。"""
        sf, project = real_env
        override = ContextOverride(foreshadowing_ids=[])

        async with sf() as s:
            repo = SQLiteForeshadowingRepository(s)
            items = await ForeshadowingSource(repo).collect(project.id, None)
            preview = _apply_override(items, ContextSourceType.FORESHADOWING, override)
            result = await _svc(s, project)._assemble_setting_context(str(project.id), {}, override)

        assert preview == [], "预览路径显式空 = 删空"
        assert "伏笔甲" not in result.get("setting", "")
        assert "伏笔乙" not in result.get("setting", "")


class TestFalsifiability:
    async def test_source_returns_open_only(self, real_env):
        """可证伪自证：真实仓储 list_open 只返回 open（底座事实）。

        若把伏笔源的白名单过滤整体删掉，上面的 ③/④/⑤ 必 FAIL ——
        本用例固化「底座确实有 resolved 行」这一前提（否则那些断言会因
        「根本没有可区分的数据」而假绿）。
        """
        sf, _project = real_env
        async with sf() as s:
            open_rows = await SQLiteForeshadowingRepository(s).list_open(_u(PID))
            all_rows, _total = await SQLiteForeshadowingRepository(s).list(_u(PID), limit=50)

        assert {f.title for f in open_rows} == {"伏笔甲", "伏笔乙"}
        assert {f.title for f in all_rows} == {"伏笔甲", "伏笔乙", "已回收伏笔"}, (
            "底座必须含 resolved 行，否则「已回收不注入」断言无法证伪"
        )

    async def test_foreshadowing_entity_status_contract(self, real_env):
        """可证伪自证：Foreshadowing 领域实体的 status 口径（open/resolved）。"""
        sf, _project = real_env
        async with sf() as s:
            fs, _total = await SQLiteForeshadowingRepository(s).list(_u(PID), limit=50)
        by_title = {f.title: f for f in fs}
        assert by_title["伏笔甲"].status is ForeshadowingStatus.OPEN
        assert by_title["已回收伏笔"].status is ForeshadowingStatus.RESOLVED
        assert isinstance(by_title["伏笔甲"], Foreshadowing)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "--no-header"]))
