"""#1472 管线链路 skill 装配 —— RED 契约（spec f39 §5.2 v1.4「管线链路装配」）。

问题（#1472 根因）：全仓 `_append_skills` 唯一调用点在写手轨
（`infrastructure/agent/agentic_writer.py`），`agent run --pipeline` 的 stage
构造（`domain/services/agent_service_stream._build_pipeline_context`）完全不碰
`skill_ids` → 用户上传 skill 在架构师/写手/审校员/修订师四阶段**静默失效**。

契约（本文件锁定）：
- stage prompt = 该 stage 对应 Agent 的 `system_prompt` + 该 Agent `skill_ids`
  命中的 skill 正文（base 前 skill 后，与写手轨同语义）；
- **四阶段各自**携带自己 Agent 的 skill（不能只修 writer 一条）；
- 负例①：未挂载到该 Agent 的 skill **不得**出现在其 prompt（防串味）；
- 负例②：Agent `skill_ids` 为空 → prompt 与装配前**逐字符一致**（零回归）。

实现前必须实测 FAIL（当前 0 命中）。
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

# 各角色 skill 正文特征词（写入 tmp skills_root，断言 prompt 携带）
_CHAR = {
    "architect": "架构方法论特征词ALPHA",
    "writer": "写作方法论特征词BRAVO",
    "auditor": "审校方法论特征词CHARLIE",
    "reviser": "修订方法论特征词DELTA",
}
_SKILL_DIR = {
    "architect": "architecture-methodology",
    "writer": "writing-methodology",
    "auditor": "audit-methodology",
    "reviser": "revision-methodology",
}


def _make_project() -> Project:
    """空配置项目（agent_order/agent_relations 空 → 走模板默认拓扑，四阶段）。"""
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


def _build_svc(agent_repo) -> AgentService:
    """装配 AgentService（Mock 仓储/stub，真实模板 + 真实 _merge_role_configs）。"""
    return AgentService(
        pipeline=MagicMock(),
        db_session=None,
        store=MagicMock(),
        project_repo=_MockProjectRepo(_make_project()),
        chapter_repo=_MockChapterRepo(),
        agent_repo=agent_repo,
    )


class _MockProjectRepo:
    def __init__(self, project: Project | None):
        self._project = project

    async def get(self, project_id: int) -> Project | None:
        return self._project


class _MockChapterRepo:
    async def get_chapter(self, chapter_id: int):
        return None


def _request() -> PipelineExecuteRequest:
    return PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="builtin:write_auto")


def _patch_skills_root(monkeypatch, tmp_path) -> None:
    """config.data_dir = tmp_path（skills_root = tmp_path/skills，镜像既有 patch 模式）。"""
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)


def _stages_by_id(stages) -> dict[str, object]:
    return {s.id: s for s in stages}


@pytest.mark.asyncio
async def test_four_stages_each_carry_own_agent_skill(monkeypatch, tmp_path) -> None:
    """四阶段各自的 prompt 都带上自己 Agent 的 skill 正文（不能只修 writer 一条）。"""
    root = tmp_path / "skills"
    for role, name in _SKILL_DIR.items():
        _write_skill(root, name, f"# {name}\n\n{_CHAR[role]}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(
        return_value=[_make_agent(role, [_SKILL_DIR[role]]) for role in _SKILL_DIR]
    )
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())
    by_id = _stages_by_id(stages)

    for role in _SKILL_DIR:
        assert role in by_id, f"模板应含 {role} 阶段"
        assert _CHAR[role] in by_id[role].agent.system_prompt, (
            f"{role} stage prompt 应携带其 Agent 的 skill 正文（#1472 当前 0 命中）"
        )


@pytest.mark.asyncio
async def test_unmounted_skill_not_in_other_agent_prompt(monkeypatch, tmp_path) -> None:
    """负例①：只挂给 writer 的 skill 不得出现在 architect 的 prompt（防串味）。

    ⚠️ #1473 语义演进（2026-10-06）：本用例原断言「architect 的 skill 不进 writer」
    依赖 #1472 的「只拼该 Agent 白名单」语义——演进后**未被任何 Agent 挂载**的 skill
    作为「通用」注入所有 Agent（architect-methodology 未被挂载 → 现进 writer），该
    断言已不成立，故移除。保留「被 writer 显式挂载者不外泄到 architect」这一**仍成立**
    的防串味契约（通用注入不得使专属 skill 外泄）。
    """
    root = tmp_path / "skills"
    for role, name in _SKILL_DIR.items():
        _write_skill(root, name, f"# {name}\n\n{_CHAR[role]}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(return_value=[_make_agent("writer", [_SKILL_DIR["writer"]])])
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())
    by_id = _stages_by_id(stages)

    assert _CHAR["writer"] in by_id["writer"].agent.system_prompt
    assert _CHAR["writer"] not in by_id["architect"].agent.system_prompt


@pytest.mark.asyncio
async def test_empty_skill_ids_prompt_byte_identical(monkeypatch, tmp_path) -> None:
    """负例②：Agent 无任何有效 skill → stage prompt 与模板装配前逐字符一致（零回归）。

    ⚠️ #1473 语义演进（2026-10-06）：库内 skill 若**未被任何 Agent 挂载**会成为
    「通用」注入所有 Agent，故「Agent skill_ids 为空」不再等价于「零注入」。本用例
    改为「库内全部 skill 均已被**其他** Agent 显式挂载」——此时无通用项，未挂载的
    architect 仍零注入，逐字符一致（原意图保留）。
    """
    root = tmp_path / "skills"
    for role, name in _SKILL_DIR.items():
        _write_skill(root, name, f"# {name}\n\n{_CHAR[role]}\n")
    _patch_skills_root(monkeypatch, tmp_path)

    # 4 个 skill 全部挂到 reviser → mounted_names 覆盖全集 → 无通用项
    agent_repo = MagicMock()
    agent_repo.list = AsyncMock(return_value=[_make_agent("reviser", list(_SKILL_DIR.values()))])
    svc = _build_svc(agent_repo)

    stages, *_ = await svc._build_pipeline_context(_request())

    # 基线：装配前模板 prompt（同一次运行的模板真源）
    template = svc._get_template("builtin:write_auto")
    base_prompt = {s.id: s.agent.system_prompt for s in template.stages}
    by_id = _stages_by_id(stages)
    architect = by_id["architect"]
    assert architect.agent.system_prompt == base_prompt["architect"]
    for char in _CHAR.values():
        assert char not in architect.agent.system_prompt
