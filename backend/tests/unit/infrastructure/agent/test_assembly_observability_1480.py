"""#1480 装配可观测面 — 基础设施层单元测试（有效技能集解析 / 挂载集合 / 缺省短路）.

覆盖 `infrastructure/agent/assembly_observability.py`：
- `collect_mounted_skill_names` 走真实 `agents.skill_ids` 数据面（general 判据 = 引用数 0）；
- `list_library_skills` 库根缺失 → 空列表；
- `build_assembly_observability` 三开关全关 → 空 dict（不改行为、不触发 DB 查询）；
- `build_observable_system_prompt` 对库中已消失的目录名防御跳过（镜像 `_append_skills`）。

依据: `specs/f6-context/spec.md` §5.1/§5.2（v1.5 #1480）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.agent import Agent
from inkflow.infrastructure.agent.assembly_observability import (
    build_assembly_observability,
    build_observable_system_prompt,
    collect_mounted_skill_names,
    list_library_skills,
    resolve_effective_skills,
)
from inkflow.infrastructure.database.repositories.agent_repo import SQLiteAgentRepository


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每测试一个全新库（镜像 test_agent_repo.py fixture）."""
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


def _bare_skills_root(tmp_path: Path) -> Path:
    """空 skill 库根（目录存在但无 SKILL.md）."""
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


class TestCollectMountedSkillNames:
    async def test_reads_agent_skill_ids(self, db_session) -> None:
        """Agent 的 skill_ids 汇总为「已挂载」集合（general 判据的反面）."""
        repo = SQLiteAgentRepository(db_session)
        await repo.add(Agent(name="写手", skill_ids=["writing-methodology"]))
        await repo.add(Agent(name="自定义", skill_ids=["audit-methodology", "my-skill"]))

        mounted = await collect_mounted_skill_names(db_session)

        assert mounted == {"writing-methodology", "audit-methodology", "my-skill"}

    async def test_empty_db_returns_empty_set(self, db_session) -> None:
        """无 Agent → 空集合（所有库内 skill 都属通用）."""
        assert await collect_mounted_skill_names(db_session) == set()


class TestListLibrarySkills:
    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        """库根不存在 → 空列表（不抛错）."""
        assert list_library_skills(tmp_path / "nope") == []

    def test_ignores_dirs_without_skill_md(self, tmp_path: Path) -> None:
        """只有含 SKILL.md 的目录算已安装 skill（其它目录/文件忽略，按名升序）."""
        root = tmp_path / "skills"
        (root / "b-skill").mkdir(parents=True)
        (root / "b-skill" / "SKILL.md").write_text("b", encoding="utf-8")
        (root / "a-skill").mkdir(parents=True)
        (root / "a-skill" / "SKILL.md").write_text("a", encoding="utf-8")
        (root / "no-md").mkdir(parents=True)
        (root / "loose.txt").write_text("x", encoding="utf-8")

        assert list_library_skills(root) == ["a-skill", "b-skill"]


class TestBuildAssemblyObservability:
    async def test_all_flags_off_returns_empty(self, tmp_path: Path) -> None:
        """三开关全关 → 空 dict，且不触碰 DB（db=None 也不炸 = 未查询）."""
        payload = await build_assembly_observability(
            db=None,  # type: ignore[arg-type]  # 全关分支必须在任何 DB 访问之前返回
            skills_root=_bare_skills_root(tmp_path),
            context_text="ctx",
            project_id=uuid.uuid4(),
            chapter_id=None,
            show_system_prompt=False,
            show_skills=False,
            show_tools=False,
        )

        assert payload == {}

    async def test_tools_only_skips_skill_resolution(self, tmp_path: Path) -> None:
        """只开 tools → 不读 skill 库/Agent 表（db=None 可证），仅回 tool id 清单."""
        payload = await build_assembly_observability(
            db=None,  # type: ignore[arg-type]  # tools 分支不触发 DB
            skills_root=tmp_path / "missing",
            context_text="ctx",
            project_id=uuid.uuid4(),
            chapter_id=None,
            show_system_prompt=False,
            show_skills=False,
            show_tools=True,
        )

        assert set(payload) == {"tools"}
        assert "search_characters" in payload["tools"]


class TestResolveEffectiveSkillsDefensive:
    def test_general_entry_skipped_when_skill_file_vanishes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """库扫描后 SKILL.md 消失（TOCTOU）→ general 分支跳过该目录名（防御语义）."""
        from inkflow.infrastructure.agent import assembly_observability as mod

        monkeypatch.setattr(mod, "list_library_skills", lambda _root: ["vanished"])

        entries = mod.resolve_effective_skills(
            skills_root=tmp_path / "skills",
            explicit_ids=[],
            mounted_names=set(),
        )

        assert entries == []


class TestBuildObservableSystemPrompt:
    def test_skips_skill_missing_from_library(self, tmp_path: Path) -> None:
        """effective 清单里库中已消失的目录名 → 查表返回 None → 跳过（不抛错）."""
        skills_root = _bare_skills_root(tmp_path)

        prompt = build_observable_system_prompt(
            skills_root=skills_root,
            context_text="## 写作要求\n续写",
            project_id=uuid.uuid4(),
            chapter_id=None,
            effective_skills=[{"name": "ghost-skill", "bytes": 1, "source": "explicit"}],
        )

        assert "小说章节写作助手" in prompt
        assert "ghost-skill" not in prompt
        assert (
            resolve_effective_skills(
                skills_root=skills_root, explicit_ids=["ghost-skill"], mounted_names=set()
            )
            == []
        )
