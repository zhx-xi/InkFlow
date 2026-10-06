"""#1480 装配可观测面 — POST /context/assemble 契约测试.

契约（`specs/f6-context/spec.md` §5.1/§5.2，v1.5 #1480）:
- 请求体新增 3 个**默认关闭**的可选 bool：`show_system_prompt` / `show_skills` / `show_tools`。
- 缺省（或全 false）→ 响应**不含** `system_prompt` / `skills` / `tools`（守住「默认关闭」）。
- `show_system_prompt=true` → `system_prompt` 非空，且含有效技能集正文特征词。
- `show_skills=true` → `skills` = `[{name, bytes, source}]`，`source ∈ {explicit, general}`；
  `bytes` = 该 SKILL.md 的 UTF-8 字节数。
- `show_tools=true` → `tools` = 装配层 tool id 清单（名称与工具目录同口径）。

RED 形态（实现前）：三键恒不存在 → 正向用例 FAIL；「默认关闭」负例 PASS（守住现状，
故负例**不依赖**新增模块，避免 RED 阶段被 import 错误污染成 ERROR）。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.core.config import config as app_config
from inkflow.domain.models.context import (
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextSourceType,
)

client = TestClient(app)

# 写手授权白名单内的内置 skill（explicit）+ 库中无人挂载的通用 skill（general）
EXPLICIT_SKILL = "writing-methodology"
GENERAL_SKILL = "my-general-skill"
EXPLICIT_MARKER = "破折号密度"  # 只出现在 explicit skill 正文
GENERAL_MARKER = "通用写作规范"  # 只出现在 general skill 正文

EXPLICIT_BODY = (
    f"---\nname: {EXPLICIT_SKILL}\ndescription: 写手方法论\n---\n\n# 写法\n\n{EXPLICIT_MARKER}\n"
)
GENERAL_BODY = (
    f"---\nname: {GENERAL_SKILL}\ndescription: 通用规范\n---\n\n# 通用\n\n{GENERAL_MARKER}\n"
)
EXPLICIT_BYTES = len(EXPLICIT_BODY.encode("utf-8"))

WRITER_TOOL_IDS = ["search_characters", "get_prior_summary", "save_draft"]


def _mock_result() -> ContextAssemblyResult:
    """最小组装结果（render_system_prompt 产物进 system_prompt 的 context 段）。"""
    return ContextAssemblyResult(
        blocks=[
            ContextBlock(
                item=ContextItem(
                    source=ContextSourceType.WRITING_REQUIREMENTS,
                    title="写作要求",
                    content="续写第5章",
                    priority=100,
                ),
                layer=ContextLayer.PROTECTED,
                token_count=10,
            )
        ],
        budget_tokens=102400,
        total_tokens=10,
        model="openai/gpt-4o",
        dropped=[],
    )


RENDERED_CONTEXT = "## 写作要求\n续写第5章"


def _stub_context_service() -> MagicMock:
    """Mock ContextService：build_context 返最小结果 + render_system_prompt 返固定文本.

    `render_system_prompt` 必须给定字符串——router 会把它作为写手轨 `context` 变量
    渲染进 system prompt（未设时 MagicMock 会污染渲染）。
    """
    mock_svc = MagicMock()
    mock_svc.build_context = AsyncMock(return_value=_mock_result())
    mock_svc.render_system_prompt = MagicMock(return_value=RENDERED_CONTEXT)
    return mock_svc


def _seed_skills(tmp_path: Path) -> Path:
    """落盘两个 skill（explicit 白名单命中 + 无人挂载的通用），返回 skills_root。"""
    skills_root = tmp_path / "skills"
    for name, body in ((EXPLICIT_SKILL, EXPLICIT_BODY), (GENERAL_SKILL, GENERAL_BODY)):
        target = skills_root / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(body, encoding="utf-8")
    return skills_root


def _post(extra: dict | None = None) -> dict:
    """发一次 assemble 请求，返回响应 JSON（断言 200）。"""
    body = {
        "project_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
        "model": "openai/gpt-4o",
        "writing_requirements": "续写第5章，保持悬疑氛围",
    }
    body.update(extra or {})
    response = client.post("/api/v1/context/assemble", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ── 负例：默认关闭（不依赖新增模块，RED 阶段即 PASS） ──────────────


@patch("inkflow.api.routers.context.get_context_service")
async def test_observability_keys_absent_by_default(mock_get_svc: MagicMock) -> None:
    """不带新字段 → 响应不含 system_prompt / skills / tools（守住「默认关闭」）。"""
    mock_get_svc.return_value = _stub_context_service()

    data = _post()

    assert "system_prompt" not in data
    assert "skills" not in data
    assert "tools" not in data
    # 既有契约键一个不少
    assert {"blocks", "budget_tokens", "total_tokens", "model", "dropped"} <= set(data)


@patch("inkflow.api.routers.context.get_context_service")
async def test_observability_keys_absent_when_flags_false(mock_get_svc: MagicMock) -> None:
    """显式传 false（三键齐全）→ 仍不含观测键（关闭语义不看「键存在」）。"""
    mock_get_svc.return_value = _stub_context_service()

    data = _post({"show_system_prompt": False, "show_skills": False, "show_tools": False})

    assert "system_prompt" not in data
    assert "skills" not in data
    assert "tools" not in data


# ── 正例：显式开启 ────────────────────────────────────────────────


@patch("inkflow.api.routers.context.get_context_service")
@patch(
    "inkflow.infrastructure.agent.assembly_observability.collect_mounted_skill_names",
    new_callable=AsyncMock,
)
async def test_show_system_prompt_contains_effective_skill_content(
    mock_mounted: AsyncMock, mock_get_svc: MagicMock, tmp_path, monkeypatch
) -> None:
    """show_system_prompt=true → 非空，且含**有效技能集**（explicit + general）正文特征词。"""
    monkeypatch.setattr(app_config, "data_dir", tmp_path)
    _seed_skills(tmp_path)
    mock_mounted.return_value = {EXPLICIT_SKILL}
    mock_get_svc.return_value = _stub_context_service()

    data = _post({"show_system_prompt": True})

    assert "system_prompt" in data
    prompt = data["system_prompt"]
    assert isinstance(prompt, str) and prompt.strip()
    # 写手轨 base（writer_agent.yaml 渲染）在场
    assert "小说章节写作助手" in prompt
    # 本次组装的 context 段在场（render_system_prompt 产物整段进 {context} 变量）
    assert RENDERED_CONTEXT in prompt
    # 有效技能集正文（explicit + general）都被 _append_skills 拼进去
    assert EXPLICIT_MARKER in prompt
    assert GENERAL_MARKER in prompt
    assert f"# 技能：{EXPLICIT_SKILL}" in prompt
    assert f"# 技能：{GENERAL_SKILL}" in prompt


@patch("inkflow.api.routers.context.get_context_service")
@patch(
    "inkflow.infrastructure.agent.assembly_observability.collect_mounted_skill_names",
    new_callable=AsyncMock,
)
async def test_show_skills_lists_effective_set_with_source_and_bytes(
    mock_mounted: AsyncMock, mock_get_svc: MagicMock, tmp_path, monkeypatch
) -> None:
    """show_skills=true → [{name, bytes, source}]；explicit/general 分类 + 真实字节数。"""
    monkeypatch.setattr(app_config, "data_dir", tmp_path)
    _seed_skills(tmp_path)
    mock_mounted.return_value = {EXPLICIT_SKILL}
    mock_get_svc.return_value = _stub_context_service()

    data = _post({"show_skills": True})

    assert "skills" in data
    skills = data["skills"]
    assert isinstance(skills, list) and skills
    by_name = {item["name"]: item for item in skills}
    assert set(by_name) == {EXPLICIT_SKILL, GENERAL_SKILL}
    assert by_name[EXPLICIT_SKILL]["source"] == "explicit"
    assert by_name[GENERAL_SKILL]["source"] == "general"
    assert by_name[EXPLICIT_SKILL]["bytes"] == EXPLICIT_BYTES
    assert by_name[GENERAL_SKILL]["bytes"] == len(GENERAL_BODY.encode("utf-8"))
    assert all({"name", "bytes", "source"} == set(item) for item in skills)


@patch("inkflow.api.routers.context.get_context_service")
@patch(
    "inkflow.infrastructure.agent.assembly_observability.collect_mounted_skill_names",
    new_callable=AsyncMock,
)
async def test_show_tools_lists_assembly_layer_tool_ids(
    mock_mounted: AsyncMock, mock_get_svc: MagicMock, tmp_path, monkeypatch
) -> None:
    """show_tools=true → tool id 列表，名称全部落在统一工具目录内（与 agent tools 同口径）。"""
    from inkflow.infrastructure.agent.tools.registry import ALL_TOOL_SPECS

    monkeypatch.setattr(app_config, "data_dir", tmp_path)
    _seed_skills(tmp_path)
    mock_mounted.return_value = {EXPLICIT_SKILL}
    mock_get_svc.return_value = _stub_context_service()

    data = _post({"show_tools": True})

    assert "tools" in data
    tools = data["tools"]
    assert isinstance(tools, list) and all(isinstance(t, str) for t in tools)
    catalog = {spec.name for spec in ALL_TOOL_SPECS}
    assert set(tools) <= catalog
    # 写手轨装配层实际传入的具名工具（独立基线，非回读实现）
    assert set(WRITER_TOOL_IDS) <= set(tools)


@patch("inkflow.api.routers.context.get_context_service")
@patch(
    "inkflow.infrastructure.agent.assembly_observability.collect_mounted_skill_names",
    new_callable=AsyncMock,
)
async def test_flags_are_independent(
    mock_mounted: AsyncMock, mock_get_svc: MagicMock, tmp_path, monkeypatch
) -> None:
    """三个开关互相独立：只开 show_tools → 不夹带 system_prompt / skills。"""
    monkeypatch.setattr(app_config, "data_dir", tmp_path)
    _seed_skills(tmp_path)
    mock_mounted.return_value = {EXPLICIT_SKILL}
    mock_get_svc.return_value = _stub_context_service()

    data = _post({"show_tools": True})

    assert "tools" in data
    assert "system_prompt" not in data
    assert "skills" not in data


@patch("inkflow.api.routers.context.get_context_service")
@patch(
    "inkflow.infrastructure.agent.assembly_observability.collect_mounted_skill_names",
    new_callable=AsyncMock,
)
async def test_unknown_whitelist_skill_is_skipped(
    mock_mounted: AsyncMock, mock_get_svc: MagicMock, tmp_path, monkeypatch
) -> None:
    """白名单里库中不存在的目录名被跳过（与 `_append_skills` 防御语义一致）。"""
    from inkflow.infrastructure.agent.assembly_observability import (
        resolve_effective_skills,
    )

    skills_root = _seed_skills(tmp_path)
    entries = resolve_effective_skills(
        skills_root=skills_root,
        explicit_ids=[EXPLICIT_SKILL, "not-installed"],
        mounted_names={EXPLICIT_SKILL},
    )
    names = [entry["name"] for entry in entries]
    assert "not-installed" not in names
    # explicit 白名单顺序在前，general（无人挂载者）在后
    assert names == [EXPLICIT_SKILL, GENERAL_SKILL]
    assert [entry["source"] for entry in entries] == ["explicit", "general"]
    assert entries[0]["bytes"] == EXPLICIT_BYTES
