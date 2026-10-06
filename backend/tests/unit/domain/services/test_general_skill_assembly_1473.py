"""#1473 通用 skill 全局生效 —— RED 契约（spec f39 §5.2 v1.5）。

问题（#1473 根因）：`_attach_agent_skills`（#1472）**只遍历 `agent.skill_ids` 白名单**
→ 库中「未被任何 Agent 挂载」的 skill（通用规范：去 AI 味、格式规范、题材规则）
谁也用不到。用户期望「一次放置、全局生效」，但当前必须逐个 Agent 挂载（内置 Agent
又不可编辑）。

契约（本文件锁定，推翻 #1472 的「只拼白名单」取集语义）：
- 有效技能集 = `agent.skill_ids`（显式挂载）∪ `{skills_root 下未被任何 Agent 挂载的}`（通用）；
- 通用 skill 对**所有** stage 自动生效；显式挂载优先于通用（同名去重）；
- 防串味仍成立：被**其他** Agent 显式挂载的 skill 不得注入本 Agent；
- 负例：库空 + 无挂载 → stage prompt 与装配前逐字符一致（零回归）。

实现前必须实测 FAIL（当前通用 skill 0 注入）。
"""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.agent_service import AgentService

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
pytestmark = pytest.mark.asyncio

# 特征词（写入 tmp skills_root，断言 prompt 携带）
_GENERAL_CHAR = "通用规范特征词GENERAL"
_GENERAL_DIR = "general-style-guide"
_MOUNTED_CHAR = "被挂载专属特征词MOUNTED"
_MOUNTED_DIR = "architect-only"
_DEDUP_CHAR = "去重特征词DEDUP"
_DEDUP_DIR = "shared-skill"


def _make_project() -> Project:
    return Project(
        id=PROJECT_ID,
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_agent(role_key: str, skill_ids: list[str]) -> SimpleNamespace:
    """Agent 真源替身（含 role_key + skill_ids，镜像 AgentRepository.list() 领域对象）。"""
    return SimpleNamespace(
        role_key=role_key,
        name=role_key,
        system_prompt=f"base::{role_key}",
        skill_ids=list(skill_ids),
    )


def _write_skill(root, name: str, content: str) -> None:
    """写 <root>/<name>/SKILL.md（文件系统真源，ADR-039 #522）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


class _MockProjectRepo:
    async def get(self, _project_id):
        return _make_project()


class _MockChapterRepo:
    async def get_chapter(self, _chapter_id):
        return None


def _build_svc(agent_repo) -> AgentService:
    """装配 AgentService（Mock 仓储/stub，真实模板 + 真实 _merge_role_configs）。"""
    return AgentService(
        pipeline=MagicMock(),
        db_session=None,
        store=MagicMock(),
        project_repo=_MockProjectRepo(),
        chapter_repo=_MockChapterRepo(),
        agent_repo=agent_repo,
    )


def _request() -> PipelineExecuteRequest:
    return PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="builtin:write_auto")


def _patch_skills_root(monkeypatch, tmp_path) -> None:
    """config.data_dir = tmp_path（skills_root = tmp_path/skills）。"""
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)


def _stages_by_id(stages) -> dict[str, object]:
    return {s.id: s for s in stages}


async def test_general_skill_injected_into_all_stages(monkeypatch, tmp_path) -> None:
    """未被任何 Agent 挂载的通用 skill → 所有 stage 的 prompt 都携带（#1473 当前 FAIL）。"""
    root = tmp_path / "skills"
    _write_skill(root, _GENERAL_DIR, f"# {_GENERAL_DIR}\n\n{_GENERAL_CHAR}\n")
    _write_skill(root, _MOUNTED_DIR, f"# {_MOUNTED_DIR}\n\n{_MOUNTED_CHAR}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(return_value=[_make_agent("writer", [_MOUNTED_DIR])])
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())
    by_id = _stages_by_id(stages)

    for stage in stages:
        assert _GENERAL_CHAR in stage.agent.system_prompt, (
            f"{stage.id} stage prompt 应携带通用 skill 正文（#1473 当前 0 注入）"
        )
    # 显式挂载的专属 skill 只进其挂载 Agent
    assert _MOUNTED_CHAR in by_id["writer"].agent.system_prompt
    assert _MOUNTED_CHAR not in by_id["architect"].agent.system_prompt


async def test_mounted_skill_is_not_general_for_others(monkeypatch, tmp_path) -> None:
    """防串味：被某 Agent 显式挂载的 skill 不算通用，不注入其他 Agent。"""
    root = tmp_path / "skills"
    _write_skill(root, _MOUNTED_DIR, f"# {_MOUNTED_DIR}\n\n{_MOUNTED_CHAR}\n")
    _write_skill(root, _GENERAL_DIR, f"# {_GENERAL_DIR}\n\n{_GENERAL_CHAR}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(return_value=[_make_agent("architect", [_MOUNTED_DIR])])
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())
    by_id = _stages_by_id(stages)

    assert _MOUNTED_CHAR in by_id["architect"].agent.system_prompt
    assert _MOUNTED_CHAR not in by_id["writer"].agent.system_prompt
    assert _MOUNTED_CHAR not in by_id["auditor"].agent.system_prompt
    # 通用仍对所有人生效
    for stage in stages:
        assert _GENERAL_CHAR in stage.agent.system_prompt


async def test_explicit_wins_over_general_no_duplication(monkeypatch, tmp_path) -> None:
    """覆盖顺序：显式挂载优先于通用——同一 skill 正文在一个 prompt 内只出现一次。"""
    root = tmp_path / "skills"
    _write_skill(root, _DEDUP_DIR, f"# {_DEDUP_DIR}\n\n{_DEDUP_CHAR}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(
        return_value=[_make_agent("writer", [_DEDUP_DIR]), _make_agent("architect", [])]
    )
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())
    by_id = _stages_by_id(stages)

    assert by_id["writer"].agent.system_prompt.count(_DEDUP_CHAR) == 1
    assert _DEDUP_CHAR not in by_id["architect"].agent.system_prompt


async def test_empty_library_and_no_mounts_byte_identical(monkeypatch, tmp_path) -> None:
    """负例：库空 + 无挂载 → stage prompt 与模板装配前逐字符一致（零回归）。"""
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(
        return_value=[
            _make_agent(role, []) for role in ("architect", "writer", "auditor", "reviser")
        ]
    )
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())

    template = svc._get_template("builtin:write_auto")
    base_prompt = {s.id: s.agent.system_prompt for s in template.stages}
    for stage in stages:
        assert stage.agent.system_prompt == base_prompt[stage.id]
