"""#1299 AI 提取链路 role_rank 三层补齐 RED 契约测试。

背景（#1299 实锤）: AI 提取创建的角色无角色等级——提取管线三层全缺:
① Prompt 模板（character_extract.yaml）未要求 LLM 输出 role_rank；
② 解析 schema（ExtractedCharacter）无该字段；
③ 落库构造（_character_extractor._merge 新建分支）未传 extra → 落库 extra={}。

现象: GUI 角色列表出现无等级徽标的角色（#679 等级选项卡过滤归不进任何档）。

本文件锁定契约:
1. ExtractedCharacter 接受 role_rank（五档枚举；非法值 → ValidationError）；
2. 新建分支落库 extra["role_rank"] 非空（LLM 返回缺失时回退 minor 并记 warning）；
3. 同名已存在角色不覆盖既有 extra.role_rank（#679 语义: 已存在角色不受影响）；
4. zh/en prompt 模板均声明 role_rank 字段（中英文用词断言，避免多语言版本漂移）。

依据: issue #1299 + specs/f9-character/spec.md + specs/f43-setting-library-gui/spec.md §2.1
（五档 role_rank）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.character import (
    Character,
    CharacterExtractRequest,
    ExtractedCharacter,
    RoleRank,
)
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._character_extractor import CharacterExtractor

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"
PROMPTS_DIR = Path(__file__).parents[4] / "src" / "inkflow" / "i18n" / "prompts"


def _payload(chars: list[dict], rels: list[dict] | None = None) -> str:
    return json.dumps({"characters": chars, "relations": rels or []}, ensure_ascii=False)


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    repo.get_relation_by_key = AsyncMock(return_value=None)
    repo.add_relation = AsyncMock(side_effect=lambda r: r)
    repo.update_relation = AsyncMock(side_effect=lambda r: r)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_repo) -> CharacterExtractor:
    pm = MagicMock(spec=PromptTemplateProtocol)
    pm.load = MagicMock(
        return_value=PromptTemplate(
            name="character_extract",
            description="t",
            system_prompt="t",
            human_prompt="{text}",
            variables=["text"],
        )
    )
    pm.render = MagicMock(
        return_value=RenderedPrompt(messages=[{"role": "user", "content": "t"}], token_estimate=1)
    )
    return CharacterExtractor(llm_client=mock_llm, prompt_manager=pm, repository=mock_repo)


class TestExtractedCharacterRoleRank:
    """② 解析 schema: ExtractedCharacter 必须承载 role_rank."""

    def test_accepts_five_rank_enum(self) -> None:
        """五档枚举值均可解析（protagonist/major/minor/scene/walkon）。"""
        for rank in RoleRank:
            ec = ExtractedCharacter.model_validate({"name": "林尘", "role_rank": rank.value})
            assert ec.role_rank == rank.value

    def test_invalid_rank_rejected(self) -> None:
        """非法等级值 → ValidationError（不静默透传）。"""
        with pytest.raises(ValidationError):
            ExtractedCharacter.model_validate({"name": "林尘", "role_rank": "boss"})

    def test_missing_rank_allowed_by_schema(self) -> None:
        """LLM 漏字段时 schema 不炸（缺省 None，由落库层回退 + warning）。"""
        assert ExtractedCharacter.model_validate({"name": "林尘"}).role_rank is None


class TestMergePersistsRoleRank:
    """③ 落库构造: 新建角色写入 extra.role_rank."""

    async def test_new_character_persists_role_rank_from_llm(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """LLM 返回 role_rank → 落库角色 extra["role_rank"] 非空且一致。"""
        mock_llm.chat.return_value = ChatResponse(
            content=_payload([{"name": "林尘", "personality": "坚韧", "role_rank": "protagonist"}]),
            model=DEFAULT_MODEL,
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        persisted = mock_repo.add.await_args.args[0]
        assert persisted.extra.get("role_rank") == "protagonist"

    async def test_new_character_missing_rank_falls_back_minor_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """LLM 漏 role_rank → 回退 minor（不静默兜底 major，那是 #1303 的病）+ warning。"""
        mock_llm.chat.return_value = ChatResponse(
            content=_payload([{"name": "林尘"}]), model=DEFAULT_MODEL
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        persisted = mock_repo.add.await_args.args[0]
        assert persisted.extra.get("role_rank") == "minor"
        assert any("角色等级" in w for w in result.warnings)

    async def test_existing_character_extra_untouched(self, extractor, mock_llm, mock_repo) -> None:
        """同名已存在角色: 更新分支保留既有 extra（不因本次提取改动等级）。"""
        existing = Character(
            id=uuid.uuid4(),
            project_id=PID,
            name="林尘",
            personality="旧",
            extra={"role_rank": "walkon"},
            created_at=TS,
            updated_at=TS,
        )
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = ChatResponse(
            content=_payload([{"name": "林尘", "personality": "新", "role_rank": "protagonist"}]),
            model=DEFAULT_MODEL,
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.updated[0].extra == {"role_rank": "walkon"}


class TestPromptTemplateDeclaresRoleRank:
    """① Prompt 模板: zh/en 均要求 LLM 输出 role_rank."""

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_template_declares_role_rank(self, lang: str) -> None:
        """模板 system_prompt 含 role_rank 字段名 —— LLM 才会输出该字段。"""
        text = (PROMPTS_DIR / lang / "character_extract.yaml").read_text(encoding="utf-8")
        assert "role_rank" in text

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_template_declares_all_five_ranks(self, lang: str) -> None:
        """模板给出五档枚举取值（LLM 才能从中选，而非臆造等级）。"""
        text = (PROMPTS_DIR / lang / "character_extract.yaml").read_text(encoding="utf-8")
        for rank in RoleRank:
            assert rank.value in text
