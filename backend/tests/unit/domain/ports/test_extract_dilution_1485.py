"""#1485 提取冲稀收敛契约（RED）— 类别归属 / 近义合并 / 粒度 / dry-run / batch_id。

被测（GREEN 才实现，RED 阶段以 import/属性/关键字缺失形态 FAIL）:

- ``inkflow.domain.services._world_extractor.WorldExtractor``
  · ``{categories}`` 变量注入（项目已有分类清单，§5.8.1）
  · 类别归一（LLM 给出项目分类之外的类别 → 空串 + warning）
  · 近义合并（归一化后互为子串 → 合并进已有条目，不新建，§5.8.2）
  · ``granularity``（coarse 每源条目上限，§5.8.3）
  · ``dry_run``（零写入预览，§5.8.4）
  · ``batch_id``（新建条目携带批次标识，§5.8.5）
- ``inkflow.domain.services._character_extractor.CharacterExtractor``：同（除类别归属）

依据: specs/f14-extraction/spec.md §5.8.1-§5.8.5（#1485，0.17.0 W5b）。

RED 预期（实现前必须 FAIL）—— 每条对应一个验收断言：
- 类别注入      → ``variables`` 缺 ``categories`` 键
- 类别归一      → 落库仍是 LLM 原值「魔法体系」
- 近义合并      → ``created`` 1 条（应为 0，走 updated）
- 粒度          → 无该关键字参数 → TypeError
- dry-run       → 无该关键字参数 → TypeError
- batch_id      → ``WorldSetting`` 无该属性 → AttributeError
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import (
    Character,
    CharacterExtractRequest,
)
from inkflow.domain.models.world import (
    WorldCategory,
    WorldExtractRequest,
    WorldSetting,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services._world_extractor import WorldExtractor

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"

# 模板建议类别（world_extract.yaml 现状）——刻意**不含**项目已有分类「修炼体系」，
# 用于复现「LLM 类别落不进项目分类」的冲稀形态。
SUGGESTED_CATEGORY = "魔法体系"
PROJECT_CATEGORY = "修炼体系"


def _setting(name: str, *, category: str = "", content: str = "") -> WorldSetting:
    """构造测试用世界观条目实体。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category=category,
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _category(name: str) -> WorldCategory:
    """构造测试用分类实体（world_categories 受控词表）。"""
    return WorldCategory(id=uuid.uuid4(), project_id=PID, name=name, created_at=TS, updated_at=TS)


def _character(
    name: str, *, personality: str = "", background: str = "", goals: str = ""
) -> Character:
    """构造测试用角色实体。"""
    return Character(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        created_at=TS,
        updated_at=TS,
    )


def _world_payload(settings: list[dict]) -> str:
    """构造 world_settings 提取输出。"""
    return json.dumps({"world_settings": settings}, ensure_ascii=False)


def _char_payload(characters: list[dict]) -> str:
    """构造 characters 提取输出（relations 恒空）。"""
    return json.dumps({"characters": characters, "relations": []}, ensure_ascii=False)


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
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说世界观信息提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_world_repo() -> MagicMock:
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.update = AsyncMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def mock_char_repo() -> MagicMock:
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    return repo


@pytest.fixture
def world_extractor(mock_llm, mock_prompt_manager, mock_world_repo) -> WorldExtractor:
    return WorldExtractor(
        llm_client=mock_llm, prompt_manager=mock_prompt_manager, repository=mock_world_repo
    )


@pytest.fixture
def char_extractor(mock_llm, mock_prompt_manager, mock_char_repo) -> CharacterExtractor:
    return CharacterExtractor(
        llm_client=mock_llm, prompt_manager=mock_prompt_manager, repository=mock_char_repo
    )


def _render_variables(mock_prompt_manager: MagicMock) -> dict:
    """取最近一次 render 的第二个实参（模板变量 dict）。"""
    args = mock_prompt_manager.render.call_args
    assert args is not None, "render 未被调用"
    return args.args[1]


# ── ① 类别归属（setting）────────────────────────────────────────────────────


class TestCategoryAttribution:
    """§5.8.1 类别归属 — 渲染注入已有分类 + 落库归一。"""

    async def test_project_categories_injected_into_render(
        self, world_extractor, mock_llm, mock_world_repo, mock_prompt_manager
    ) -> None:
        """渲染模板必须携带项目已有分类清单（variables["categories"]）。"""
        mock_world_repo.list_world_categories = AsyncMock(
            return_value=[(_category(PROJECT_CATEGORY), 0)]
        )
        mock_llm.chat.return_value = _ok_response(_world_payload([]))

        await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        variables = _render_variables(mock_prompt_manager)
        assert "categories" in variables, "渲染变量必须注入项目已有分类清单"
        assert list(variables["categories"]) == [PROJECT_CATEGORY]

    async def test_unknown_category_falls_back_to_blank(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """LLM 类别不在项目分类中 → 落空串（未分类）+ warning（不再原样落库）。"""
        mock_world_repo.list_world_categories = AsyncMock(
            return_value=[(_category(PROJECT_CATEGORY), 0)]
        )
        mock_llm.chat.return_value = _ok_response(
            _world_payload(
                [{"name": "炼气期", "category": SUGGESTED_CATEGORY, "content": "入门境界"}]
            )
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert len(result.created) == 1
        assert result.created[0].category == "", "项目分类之外的类别必须归一为空串"
        assert any("不在项目分类中" in w for w in result.warnings)

    async def test_known_category_is_kept(self, world_extractor, mock_llm, mock_world_repo) -> None:
        """LLM 类别命中项目已有分类 → 原样落库（正向守护）。"""
        mock_world_repo.list_world_categories = AsyncMock(
            return_value=[(_category(PROJECT_CATEGORY), 0)]
        )
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "炼气期", "category": PROJECT_CATEGORY, "content": "c"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created[0].category == PROJECT_CATEGORY
        assert not any("不在项目分类中" in w for w in result.warnings)

    async def test_project_without_categories_keeps_llm_value(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """反向守护：项目无任何分类时不归一（避免无受控词表项目类别被清空）。"""
        mock_world_repo.list_world_categories = AsyncMock(return_value=[])
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "炼气期", "category": SUGGESTED_CATEGORY, "content": "c"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created[0].category == SUGGESTED_CATEGORY


# ── ② 近义合并（world + character）─────────────────────────────────────────


class TestSynonymMergeWorld:
    """§5.8.2 近义合并 — setting。"""

    async def test_synonym_merges_into_existing_entry(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """近义（归一化后互为子串）→ 合并进已有条目，不新建。"""
        existing = _setting("青云门", content="东洲第一大派。")
        mock_world_repo.list_all_active = AsyncMock(return_value=[existing])
        mock_world_repo.get_by_name = AsyncMock(return_value=None)
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "青云门 门派", "category": "", "content": "以剑修闻名。"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created == [], "近义条目不得新建（冲稀根因）"
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.id == existing.id
        assert merged.name == "青云门", "合并保留已有条目名"
        assert "东洲第一大派。" in merged.content
        assert "以剑修闻名。" in merged.content
        assert mock_world_repo.add.await_count == 0
        assert any("近义" in w for w in result.warnings)

    async def test_unrelated_entry_still_creates(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """反向守护：无包含关系的条目必须新建（不得误合并）。"""
        mock_world_repo.list_all_active = AsyncMock(return_value=[_setting("青云门")])
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "落霞谷", "category": "", "content": "西境秘境。"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert len(result.created) == 1
        assert result.created[0].name == "落霞谷"

    async def test_short_substring_not_merged(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """反向守护：短子串（占比 < 50%）不得误判近义。"""
        mock_world_repo.list_all_active = AsyncMock(return_value=[_setting("青云门")])
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "青云门落霞谷外传纪事", "category": "", "content": "c"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert len(result.created) == 1, "长度占比不足不得视为近义"

    async def test_repeat_extraction_does_not_grow(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """跑两次同一章 → 第二次零新增（冲稀验收断言）。"""
        payload = _world_payload([{"name": "灵气复苏", "category": "", "content": "天地灵气活跃"}])
        mock_llm.chat.return_value = _ok_response(payload)

        req = WorldExtractRequest(project_id=PID, text="t")
        first = await world_extractor.extract(req, default_model=DEFAULT_MODEL)
        assert len(first.created) == 1

        stored = _setting("灵气复苏", content="天地灵气活跃")
        mock_world_repo.list_all_active = AsyncMock(return_value=[stored])
        mock_world_repo.get_by_name = AsyncMock(return_value=stored)

        second = await world_extractor.extract(req, default_model=DEFAULT_MODEL)
        assert second.created == [], "重复提取不得再新增条目"
        assert second.updated == [], "字段无变化 → 幂等跳过"

        third = await world_extractor.extract(req, default_model=DEFAULT_MODEL)
        assert third.created == [], "第三次仍不得增长（不线性冲稀）"

    async def test_two_synonyms_of_same_entry_accumulate_once(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """同批两条近义条目 → 累积合并（第二次基于已合并内容，不丢前一段）。"""
        existing = _setting("青云门", content="旧")
        mock_world_repo.list_all_active = AsyncMock(return_value=[existing])
        mock_llm.chat.return_value = _ok_response(
            _world_payload(
                [
                    {"name": "青云门 派", "category": "", "content": "甲"},
                    {"name": "青云门宗", "category": "", "content": "乙"},
                ]
            )
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created == []
        assert len(result.updated) == 2
        assert result.updated[-1].content == "旧\n\n甲\n\n乙", (
            "第二次近义合并必须基于已合并内容（不得丢失前一次追加）"
        )
        assert sum(1 for w in result.warnings if "近义" in w) == 2


class TestSynonymMergeCharacter:
    """§5.8.2 近义合并 — character。"""

    async def test_synonym_merges_into_existing_character(
        self, char_extractor, mock_llm, mock_char_repo
    ) -> None:
        """近义角色名（含后缀）→ 合并进已有角色，不新建。"""
        existing = _character("林晚", personality="外冷内热。")
        mock_char_repo.list_all = AsyncMock(return_value=[existing])
        mock_char_repo.get_by_name = AsyncMock(return_value=None)
        mock_llm.chat.return_value = _ok_response(
            _char_payload(
                [{"name": "林晚 女主", "personality": "剑修天才。", "role_rank": "major"}]
            )
        )

        result = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert result.created == []
        assert len(result.updated) == 1
        assert result.updated[0].id == existing.id
        assert result.updated[0].name == "林晚"
        assert "剑修天才。" in result.updated[0].personality
        assert mock_char_repo.add.await_count == 0
        assert any("近义" in w for w in result.warnings)

    async def test_unrelated_character_still_creates(
        self, char_extractor, mock_llm, mock_char_repo
    ) -> None:
        """反向守护：无关角色必须新建。"""
        mock_char_repo.list_all = AsyncMock(return_value=[_character("林晚")])
        mock_llm.chat.return_value = _ok_response(
            _char_payload([{"name": "沈砚", "personality": "寡言。", "role_rank": "major"}])
        )

        result = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )

        assert len(result.created) == 1
        assert result.created[0].name == "沈砚"


# ── ③ 粒度控制 ─────────────────────────────────────────────────────────────


class TestGranularity:
    """§5.8.3 粒度 — coarse 每源条目上限，条目数严格少于 fine。"""

    @staticmethod
    def _many_world_settings(n: int) -> str:
        return _world_payload(
            [{"name": f"设定{i}", "category": "", "content": f"内容{i}"} for i in range(1, n + 1)]
        )

    async def test_coarse_yields_fewer_entries_than_fine(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """同一 LLM 输出下 coarse 落库条目数严格少于 fine。"""
        from inkflow.domain.models.extraction import Granularity

        payload = self._many_world_settings(8)
        mock_llm.chat.return_value = _ok_response(payload)
        mock_world_repo.list_all_active = AsyncMock(return_value=[])
        req = WorldExtractRequest(project_id=PID, text="t")

        fine = await world_extractor.extract(
            req, default_model=DEFAULT_MODEL, granularity=Granularity.FINE
        )
        coarse = await world_extractor.extract(
            req, default_model=DEFAULT_MODEL, granularity=Granularity.COARSE
        )

        assert len(fine.created) == 8
        assert len(coarse.created) < len(fine.created), "coarse 必须显著更少"
        assert any("coarse" in w for w in coarse.warnings)

    async def test_coarse_hint_injected_into_render(
        self, world_extractor, mock_llm, mock_world_repo, mock_prompt_manager
    ) -> None:
        """coarse 必须在渲染变量中注入粗粒度指令（granularity_hint）。"""
        from inkflow.domain.models.extraction import Granularity

        mock_llm.chat.return_value = _ok_response(_world_payload([]))
        await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            granularity=Granularity.COARSE,
        )

        variables = _render_variables(mock_prompt_manager)
        assert "granularity_hint" in variables
        assert variables["granularity_hint"], "coarse 指令不得为空"

    async def test_character_coarse_caps_entries(
        self, char_extractor, mock_llm, mock_char_repo
    ) -> None:
        """character 同样受 coarse 上限约束。"""
        from inkflow.domain.models.extraction import Granularity

        mock_llm.chat.return_value = _ok_response(
            _char_payload(
                [
                    {"name": f"角色{i}", "personality": "p", "role_rank": "minor"}
                    for i in range(1, 9)
                ]
            )
        )
        mock_char_repo.list_all = AsyncMock(return_value=[])

        fine = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        coarse = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            granularity=Granularity.COARSE,
        )

        assert len(fine.created) == 8
        assert len(coarse.created) < len(fine.created)


# ── ④ dry-run ─────────────────────────────────────────────────────────────


class TestDryRun:
    """§5.8.4 预览 — 计数正确且零写入。"""

    async def test_dry_run_world_zero_writes(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """dry_run → created/updated 计数正确，但 repo 零写入。"""
        existing = _setting("灵气复苏", content="旧")
        mock_world_repo.list_all_active = AsyncMock(return_value=[existing])
        mock_world_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _world_payload(
                [
                    {"name": "灵气复苏", "category": "", "content": "新"},
                    {"name": "宗门等级", "category": "", "content": "三等"},
                ]
            )
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            dry_run=True,
        )

        assert len(result.updated) == 1, "将更新的条目应计入预览"
        assert len(result.created) == 1, "将新增的条目应计入预览"
        assert mock_world_repo.add.await_count == 0, "dry-run 不得落库"
        assert mock_world_repo.update.await_count == 0, "dry-run 不得更新"
        assert all(s.batch_id is None for s in result.created)

    async def test_dry_run_character_zero_writes(
        self, char_extractor, mock_llm, mock_char_repo
    ) -> None:
        """character dry_run → 计数正确且零写入。"""
        mock_char_repo.list_all = AsyncMock(return_value=[])
        mock_llm.chat.return_value = _ok_response(
            _char_payload([{"name": "林晚", "personality": "p", "role_rank": "major"}])
        )

        result = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            dry_run=True,
        )

        assert len(result.created) == 1
        assert mock_char_repo.add.await_count == 0


# ── ⑤ batch_id ────────────────────────────────────────────────────────────


class TestBatchId:
    """§5.8.5 批次标识 — 新建条目携带同一 batch_id，dry-run 不携带。"""

    async def test_created_entries_share_batch_id(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """同一次 run 的新建条目共享同一 batch_id。"""
        mock_world_repo.list_all_active = AsyncMock(return_value=[])
        mock_llm.chat.return_value = _ok_response(
            _world_payload(
                [
                    {"name": "甲", "category": "", "content": "c1"},
                    {"name": "乙", "category": "", "content": "c2"},
                ]
            )
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            batch_id="ext-batch-001",
        )

        assert len(result.created) == 2
        assert {s.batch_id for s in result.created} == {"ext-batch-001"}

    async def test_updated_entry_keeps_its_original_batch_id(
        self, world_extractor, mock_llm, mock_world_repo
    ) -> None:
        """被更新的条目不得改写原 batch_id（保护更早批次可回滚性）。"""
        existing = _setting("灵气复苏", content="旧")
        existing = existing.model_copy(update={"batch_id": "ext-older"})
        mock_world_repo.list_all_active = AsyncMock(return_value=[existing])
        mock_world_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _world_payload([{"name": "灵气复苏", "category": "", "content": "新"}])
        )

        result = await world_extractor.extract(
            WorldExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            batch_id="ext-batch-new",
        )

        assert len(result.updated) == 1
        assert result.updated[0].batch_id == "ext-older"

    async def test_character_created_entries_share_batch_id(
        self, char_extractor, mock_llm, mock_char_repo
    ) -> None:
        """character 新建条目同样携带 batch_id。"""
        mock_char_repo.list_all = AsyncMock(return_value=[])
        mock_llm.chat.return_value = _ok_response(
            _char_payload([{"name": "林晚", "personality": "p", "role_rank": "major"}])
        )

        result = await char_extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"),
            default_model=DEFAULT_MODEL,
            batch_id="ext-batch-char",
        )

        assert result.created[0].batch_id == "ext-batch-char"
