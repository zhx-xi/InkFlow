"""#835 大纲强制树形结构 — 后端 RED 契约测试（决策点 2.A 修订 + AI 生成器建链）。

本次变更（2026-08-31 issue #835，spec f43 v1.5）:
- 移除「孤立章合法」分支 → `level=chapter` 必须挂 `level=volume` 父大纲，否则 422
  （OutlineHierarchyError）；同时 `level=volume` 必须挂 `level=overall` 父大纲。
- AI 生成器 GeneratedOutline 加 `level`（默认 overall）/`parent`（父大纲名引用）字段，
  落库建链（默认生成整体=overall 根；chapter/volume 通过 parent 名解析挂父）。

契约（service 轨，全 Mock repo）:
- GC1 create level=chapter + parent_id=None（孤立章）→ OutlineHierarchyError（RED：现在合法）
- GC2 create level=volume + parent_id=None → OutlineHierarchyError（RED：现在合法）
- GC3 create level=overall + parent_id 非空 → OutlineHierarchyError（守卫，现绿）
- GC4 合法树 overall→volume→chapter → 成功（守卫，现绿）
- GC5 create level=chapter 挂 volume → 成功（守卫，现绿）
- GC6 update 清除 chapter 的 parent（置孤儿）→ OutlineHierarchyError（RED：现在合法清空）

契约（AI 生成器轨，Mock LLM/Prompt/Repo）:
- GC7 GeneratedOutline 含 level（默认 overall）/parent（默认 None）+ level 非法校验
- GC8 generate（outline 无 level）→ 落库 outline level=overall、parent_id=None
  （RED：现落库为孤儿 chapter）
- GC9 generate（outline level=chapter + parent 名）→ 落库 level=chapter、
  parent_id=解析的父大纲 id（RED：现落库不建链）

依据: specs/f43-setting-library-gui/spec.md §2.8 决策点 2.A + §5.2 生成模板。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.outline import (
    GeneratedOutline,
    Outline,
    OutlineGenerateRequest,
    OutlineUpdate,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.outline_errors import OutlineHierarchyError
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services.outline_service import OutlineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _outline(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    level: str = "chapter",
    parent_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试用大纲实体（三级字段透传）. """
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        level=level,
        parent_id=parent_id,
        chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


# ── service 轨 fixture ────────────────────────────────────────


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 默认全方法可用. """
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.update = AsyncMock(side_effect=lambda o: o)
    return repo


def _make_service(repo: MagicMock) -> OutlineService:
    return OutlineService(repository=repo)


# ── AI 生成器轨 fixture ───────────────────────────────────────


def _payload(outline: dict | None = None, arcs: list[dict] | None = None) -> str:
    """构造合法生成 JSON 输出（outline/arcs/plot_points 三层）. """
    return json.dumps(
        {
            "outline": outline
            if outline is not None
            else {"name": "整本大纲", "description": "总体设计"},
            "arcs": arcs or [],
            "plot_points": [],
        },
        ensure_ascii=False,
    )


def _ok_response(payload: str) -> ChatResponse:
    return ChatResponse(content=payload, model=DEFAULT_MODEL)


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name="outline_generate",
        description="Outline generation template",
        system_prompt="你是小说大纲规划师。输出严格 JSON。",
        human_prompt="项目信息：\n{project_info}\n\n创作约束：\n{prompt}",
        variables=["project_info", "prompt", "num_chapters"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说大纲规划师。输出严格 JSON。"},
                {"role": "user", "content": "项目信息：\n项目名：雾都谜案"},
            ],
            token_estimate=80,
        )
    )
    return pm


@pytest.fixture
def mock_gen_repo() -> MagicMock:
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get_arc_by_name = AsyncMock(return_value=None)
    repo.add_arc = AsyncMock(side_effect=lambda a: a)
    repo.add_point = AsyncMock(side_effect=lambda p: p)
    return repo


@pytest.fixture
def generator(mock_llm, mock_prompt_manager, mock_gen_repo) -> OutlineGenerator:
    return OutlineGenerator(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_gen_repo,
    )


# ── GC1-GC6: service 层强制树形 ────────────────────────────────


class TestOutlineTreeGuard:
    """#835 强制树形：孤立章/孤立卷 拒绝，合法树成功."""

    @pytest.mark.asyncio
    async def test_gc1_create_orphan_chapter_rejected(self, mock_repo) -> None:
        """GC1 create level=chapter + parent_id=None（孤立章）→ 422 OutlineHierarchyError. """
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "孤立章", level="chapter", parent_id=None)

    @pytest.mark.asyncio
    async def test_gc2_create_volume_without_overall_parent_rejected(self, mock_repo) -> None:
        """GC2 create level=volume + parent_id=None → 422 OutlineHierarchyError. """
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "卷甲", level="volume", parent_id=None)

    @pytest.mark.asyncio
    async def test_gc3_create_overall_with_parent_rejected(self, mock_repo) -> None:
        """GC3 create level=overall + parent_id 非空 → 422（overall 不允许挂父）. """
        svc = _make_service(mock_repo)
        with pytest.raises(OutlineHierarchyError):
            await svc.create_outline(PID, "整本", level="overall", parent_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_gc4_valid_tree_overall_volume_chapter_succeeds(self, mock_repo) -> None:
        """GC4 合法树 overall→volume→chapter → 全部成功，父链正确. """
        overall = _outline("整本", level="overall")
        volume = _outline("卷一", level="volume", parent_id=overall.id)
        parent_map = {overall.id.int: overall, volume.id.int: volume}

        async def fake_get(pk):
            return parent_map.get(pk)

        mock_repo.get = fake_get
        svc = _make_service(mock_repo)

        o = await svc.create_outline(PID, "整本", level="overall", parent_id=None)
        assert o.level == "overall"
        assert o.parent_id is None

        v = await svc.create_outline(PID, "卷一", level="volume", parent_id=overall.id)
        assert v.level == "volume"
        assert v.parent_id == overall.id

        c = await svc.create_outline(PID, "第一章", level="chapter", parent_id=volume.id)
        assert c.level == "chapter"
        assert c.parent_id == volume.id

    @pytest.mark.asyncio
    async def test_gc5_create_chapter_under_volume_succeeds(self, mock_repo) -> None:
        """GC5 create level=chapter 挂 volume → 成功. """
        volume = _outline("卷一", level="volume")
        mock_repo.get = AsyncMock(return_value=volume)
        svc = _make_service(mock_repo)
        c = await svc.create_outline(PID, "第一章", level="chapter", parent_id=volume.id)
        assert c.level == "chapter"
        assert c.parent_id == volume.id

    @pytest.mark.asyncio
    async def test_gc6_update_clears_chapter_parent_rejected(self, mock_repo) -> None:
        """GC6 update 清除 chapter 的 parent（置孤立章）→ 422 OutlineHierarchyError. """
        existing = _outline("第一章", level="chapter", parent_id=uuid.uuid4())
        mock_repo.get = AsyncMock(return_value=existing)
        svc = _make_service(mock_repo)
        update = OutlineUpdate(parent_id="")
        with pytest.raises(OutlineHierarchyError):
            await svc.update_outline(existing.id, update)


# ── GC7-GC9: AI 生成器建链 ─────────────────────────────────────


class TestOutlineGeneratorTreeGuard:
    """#835 AI 生成器 GeneratedOutline 加 level/parent，落库建链."""

    def test_gc7_generated_outline_has_level_and_parent(self) -> None:
        """GC7 GeneratedOutline 含 level（默认 overall）/parent（默认 None）+ level 非法校验. """
        g = GeneratedOutline(level="overall")
        assert g.level == "overall"
        assert g.parent is None

        g2 = GeneratedOutline(level="volume", parent="卷一")
        assert g2.level == "volume"
        assert g2.parent == "卷一"

        with pytest.raises((ValueError, ValidationError)):
            GeneratedOutline(level="bogus")

    @pytest.mark.asyncio
    async def test_gc8_generate_persists_overall_root(
        self, generator, mock_llm, mock_gen_repo
    ) -> None:
        """GC8 generate（outline 无 level）→ 落库 outline=overall 根（非孤立章）. """
        mock_llm.chat.return_value = _ok_response(
            _payload(outline={"name": "整本大纲", "description": "总体设计"})
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.outline is not None
        assert result.outline.level == "overall"
        assert result.outline.parent_id is None

    @pytest.mark.asyncio
    async def test_gc9_generate_chapter_links_parent_by_name(
        self, generator, mock_llm, mock_gen_repo
    ) -> None:
        """GC9 generate（outline level=chapter + parent 名）→ 落库链接父大纲. """
        volume = _outline("卷一", level="volume")

        async def fake_get_by_name(pid, name):
            if name == "卷一":
                return volume
            return None

        mock_gen_repo.get_by_name = fake_get_by_name
        mock_llm.chat.return_value = _ok_response(
            _payload(outline={"name": "第一章", "level": "chapter", "parent": "卷一"})
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.outline is not None
        assert result.outline.level == "chapter"
        assert result.outline.parent_id == volume.id
