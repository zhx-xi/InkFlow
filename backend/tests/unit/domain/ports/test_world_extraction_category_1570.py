"""F10 世界观提取类别严格校验（#1570）— 未注册类别拒绝而非静默写空.

拍板（用户 2026-10-10）：
1. 提取遇**未注册类别** → 返回明确错误（**列出缺失的分类名**）+ 该批次**正式表零写入**，
   **不得**静默落库为未分类；
2. 由 agent / CLI 收到拒绝后**显式建类**（`world category add` / `POST /world-categories`）
   再重试提取；
3. **禁止**产品侧自动建类（不做 `auto-create`）。

与 `#1482` 的语义区分（**不回归**）：`world copy --auto-create-categories` 是**复制路径**的
用户显式开关；本单约束的是**提取路径**的默认行为。二者不冲突。

与 `#722`/`#1321` 的边界：**空类别**（LLM 主动留空，prompt 明确允许「无法判断时留空」）
不在拒绝范围，维持既有「落未分类」语义；拒绝仅针对**非空但未注册**的类别。

RED（GREEN 前）预期：
- `WorldCategoryNotRegisteredError` 尚不存在 → 模块级 ImportError（整文件 RED）；
- 且当前实现对未注册类别**静默归空并落库**（`repo.add` 被调用）。

依据: specs/f14-extraction/spec.md §5.8.1（#1570 修订）+ specs/f10-world-settings/spec.md §2.2。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import (
    WorldCategory,
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.world_errors import (
    WorldCategoryMissingError,
    WorldCategoryNotRegisteredError,
    WorldServiceError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _setting(name: str, *, category: str = "", content: str = "") -> WorldSetting:
    """构造测试用世界观条目实体（时间戳固定，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category=category,
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _cats(*names: str) -> list[tuple[WorldCategory, int]]:
    """构造 `list_world_categories` 返回值（分类实体 + 条目数）。"""
    return [
        (WorldCategory(id=uuid.uuid4(), project_id=PID, name=n, created_at=TS, updated_at=TS), 0)
        for n in names
    ]


def _payload(settings: list[dict]) -> str:
    return json.dumps({"world_settings": settings}, ensure_ascii=False)


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
        name="world_extract",
        description="World extraction template",
        system_prompt="你是小说世界观信息提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text", "categories", "granularity_hint"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[{"role": "user", "content": "章节文本：\n测试文本"}],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    """仓储替身：默认**未配置** `list_world_categories`（→ 非列表，校验跳过）。

    需要类别校验用例各自覆盖 `list_world_categories`。
    """
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.update = AsyncMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> WorldExtractor:
    return WorldExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_repo,
    )


class TestUnregisteredCategoryRejected:
    """提取遇未注册类别 → 拒绝（列出缺失分类名）+ 零写入。"""

    async def test_rejects_and_lists_missing_names_with_zero_write(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """一批 3 条（1 已注册 + 2 未注册）→ 整批拒绝，正式表零写入。"""
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定"))
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"name": "北方大陆", "category": "地理", "content": "雪原"},
                    {"name": "宗门体系", "category": "制度", "content": "三等"},
                    {"name": "灵气", "category": "背景设定", "content": "活跃"},
                ]
            )
        )

        with pytest.raises(WorldCategoryNotRegisteredError) as excinfo:
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )

        assert excinfo.value.missing == ["地理", "制度"]
        msg = str(excinfo.value)
        assert "地理" in msg
        assert "制度" in msg
        # 已注册分类不算缺失
        assert "背景设定" not in msg
        # 该批次正式表零写入（含已注册类别的那一条也不落库）
        assert mock_repo.add.await_count == 0
        assert mock_repo.update.await_count == 0

    async def test_missing_names_are_deduped_in_first_seen_order(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """重复的未注册类别只列一次（保留首次出现顺序），错误可读、可据以建类。"""
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定"))
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"name": "甲", "category": "制度", "content": ""},
                    {"name": "乙", "category": "地理", "content": ""},
                    {"name": "丙", "category": "制度", "content": ""},
                    {"name": "丁", "category": " 地理 ", "content": ""},
                ]
            )
        )

        with pytest.raises(WorldCategoryNotRegisteredError) as excinfo:
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )

        assert excinfo.value.missing == ["制度", "地理"]
        # 带空白的「 地理 」归一后与「地理」同一条，不重复列出
        assert len(excinfo.value.missing) == 2
        assert mock_repo.add.await_count == 0

    async def test_retry_after_registering_categories_succeeds(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """agent/CLI 显式建类后重试 → 成功落库且类别正确。"""
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定", "地理", "制度"))
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"name": "北方大陆", "category": "地理", "content": "雪原"},
                    {"name": "宗门体系", "category": "制度", "content": "三等"},
                    {"name": "灵气", "category": "背景设定", "content": "活跃"},
                ]
            )
        )

        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert {s.name: s.category for s in result.created} == {
            "北方大陆": "地理",
            "宗门体系": "制度",
            "灵气": "背景设定",
        }
        assert mock_repo.add.await_count == 3
        assert result.warnings == []

    async def test_project_without_categories_rejects_nonempty_category(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """项目**无任何分类**时，LLM 产出的非空类别同样未注册 → 拒绝（不再原样落库）。"""
        mock_repo.list_world_categories = AsyncMock(return_value=[])
        mock_llm.chat.return_value = _ok_response(
            _payload([{"name": "北方大陆", "category": "地理", "content": "雪原"}])
        )

        with pytest.raises(WorldCategoryNotRegisteredError) as excinfo:
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )

        assert excinfo.value.missing == ["地理"]
        assert mock_repo.add.await_count == 0

    async def test_dry_run_rejects_unregistered_category(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """零写入预览（dry_run）同样拒绝——不因「预览」而放过未注册类别。"""
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定"))
        mock_llm.chat.return_value = _ok_response(
            _payload([{"name": "北方大陆", "category": "地理", "content": "雪原"}])
        )

        with pytest.raises(WorldCategoryNotRegisteredError):
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"),
                default_model=DEFAULT_MODEL,
                dry_run=True,
            )

        assert mock_repo.add.await_count == 0

    async def test_update_path_rejected_before_write(self, extractor, mock_llm, mock_repo) -> None:
        """命中已有条目的更新路径同样先拒绝——不得以「覆盖更新」绕过。"""
        existing = _setting(name="灵气复苏", category="背景设定", content="旧内容")
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定"))
        mock_llm.chat.return_value = _ok_response(
            _payload([{"name": "灵气复苏", "category": "地理", "content": "新内容"}])
        )

        with pytest.raises(WorldCategoryNotRegisteredError):
            await extractor.extract(
                WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )

        assert mock_repo.add.await_count == 0
        assert mock_repo.update.await_count == 0


class TestCategoryStrictnessBoundaries:
    """边界：空类别维持未分类语义；仓储不支持分类查询时保持既有语义。"""

    async def test_empty_category_still_allowed(self, extractor, mock_llm, mock_repo) -> None:
        """LLM 主动留空（prompt 允许）→ 落未分类，不拒绝（防过严）。"""
        mock_repo.list_world_categories = AsyncMock(return_value=_cats("背景设定"))
        mock_llm.chat.return_value = _ok_response(
            _payload(
                [
                    {"name": "边陲小镇", "category": "", "content": "偏远"},
                    {"name": "无名之海", "content": "无类别键"},
                ]
            )
        )

        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert len(result.created) == 2
        assert all(s.category == "" for s in result.created)
        assert mock_repo.add.await_count == 2

    async def test_repo_without_category_support_preserves_legacy_semantics(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """仓储替身不支持分类清单（非列表返回）→ 跳过校验（既有单测契约，不回归）。"""
        mock_llm.chat.return_value = _ok_response(
            _payload([{"name": "灵气复苏", "category": "设定", "content": "x"}])
        )

        result = await extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created[0].category == "设定"


class TestCategoryErrorContract:
    """错误类契约：可读消息 + 结构化 missing 列表 + 422 语义归属。"""

    def test_error_lists_missing_names_and_is_service_error(self) -> None:
        err = WorldCategoryNotRegisteredError(["地理", "制度"])
        assert err.missing == ["地理", "制度"]
        assert "地理" in str(err) and "制度" in str(err)
        # 与 #1321 的「单个分类缺失」错误同属 422 业务校验族，但语义区分：
        assert isinstance(err, WorldServiceError)
        assert not isinstance(err, WorldCategoryMissingError)
