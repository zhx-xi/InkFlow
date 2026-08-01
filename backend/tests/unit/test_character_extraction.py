"""F9 角色提取管线单元测试 — Mock LLM + Mock PromptManager + Mock Repo.

覆盖 spec §9「提取（Mock LLM，遵循 ADR-015）」全部场景:
合法 JSON 全量落库 / 同名更新与幂等性 / 软删同名新建 / 非法条目跳过 /
不可解析关系引用 / 围栏输出 / 修复重试与异常透传 / 空角色列表 /
模板与模型参数断言。

依据: specs/f9-character-service/spec.md §5 + §9 测试策略。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterRelation,
)
from inkflow.domain.ports.character_errors import CharacterExtractionError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._character_extractor import (
    CharacterExtractor,
    _extract_json_fragment,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _char(
    name: str,
    *,
    personality: str = "",
    background: str = "",
    goals: str = "",
    is_deleted: bool = False,
) -> Character:
    """构造测试用角色实体（默认时间戳固定，便于断言）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        is_deleted=is_deleted,
        created_at=TS,
        updated_at=TS,
    )


def _rel(
    from_char: Character, to_char: Character, *, relation_type: str, description: str = ""
) -> CharacterRelation:
    """构造测试用关系实体。"""
    return CharacterRelation(
        id=uuid.uuid4(),
        project_id=PID,
        from_character_id=from_char.id,
        to_character_id=to_char.id,
        relation_type=relation_type,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _payload(chars: list[dict] | None = None, rels: list[dict] | None = None) -> str:
    """构造合法提取 JSON 输出。"""
    return json.dumps({"characters": chars or [], "relations": rels or []}, ensure_ascii=False)


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
        name="character_extract",
        description="Character extraction template",
        system_prompt="你是小说角色信息提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说角色信息提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda c: c)
    repo.update = AsyncMock(side_effect=lambda c: c)
    repo.get_relation_by_key = AsyncMock(return_value=None)
    repo.add_relation = AsyncMock(side_effect=lambda r: r)
    repo.update_relation = AsyncMock(side_effect=lambda r: r)
    return repo


@pytest.fixture
def extractor(mock_llm, mock_prompt_manager, mock_repo) -> CharacterExtractor:
    return CharacterExtractor(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_repo,
    )


class TestCharacterExtractor:
    """提取管线测试 — 解析 / 重试 / 合并 / 幂等（Mock LLM）。"""

    async def test_valid_json_creates_characters_and_relations(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """合法 JSON → 全部落库，created/relations_created 计数正确。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                chars=[
                    {
                        "name": "林尘",
                        "personality": "坚韧",
                        "background": "山村少年",
                        "goals": "变强",
                    },
                    {
                        "name": "苏瑶",
                        "personality": "聪慧",
                        "background": "宗门弟子",
                        "goals": "寻亲",
                    },
                ],
                rels=[{"from": "林尘", "to": "苏瑶", "type": "同伴", "description": "结伴同行"}],
            )
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="章节文本"), default_model=DEFAULT_MODEL
        )
        assert isinstance(result, CharacterExtractionResult)
        assert len(result.created) == 2
        assert result.updated == []
        assert len(result.relations_created) == 1
        assert result.relations_updated == []
        assert result.warnings == []
        assert result.model == DEFAULT_MODEL
        assert mock_repo.add.await_count == 2
        assert {c.name for c in result.created} == {"林尘", "苏瑶"}
        assert mock_repo.add_relation.await_count == 1
        rel = mock_repo.add_relation.await_args.args[0]
        by_name = {c.name: c for c in result.created}
        assert rel.from_character_id == by_name["林尘"].id
        assert rel.to_character_id == by_name["苏瑶"].id
        assert rel.relation_type == "同伴"
        assert rel.description == "结伴同行"

    async def test_updates_existing_same_name_non_empty_override(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """同名已存在 → 更新（非空字段覆盖，空值不覆盖），计入 updated。"""
        existing = _char(name="林尘", personality="旧性格", background="旧背景", goals="旧目标")
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload(
                chars=[{"name": "林尘", "personality": "新性格", "background": "", "goals": None}]
            )
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert len(result.updated) == 1
        merged = result.updated[0]
        assert merged.personality == "新性格"
        assert merged.background == "旧背景"  # 空串不覆盖
        assert merged.goals == "旧目标"  # None 不覆盖
        assert mock_repo.update.await_count == 1
        assert mock_repo.add.await_count == 0

    async def test_update_preserves_unrelated_fields(self, extractor, mock_llm, mock_repo) -> None:
        """更新时保留 group_id / extra / created_at / is_deleted 等无关字段。"""
        group_id = uuid.uuid4()
        existing = Character(
            id=uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001"),
            project_id=PID,
            name="林尘",
            personality="旧性格",
            group_id=group_id,
            extra={"tags": ["主角"]},
            created_at=TS,
            updated_at=TS,
        )
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload(chars=[{"name": "林尘", "personality": "新"}])
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        merged = result.updated[0]
        assert merged.id == existing.id
        assert merged.name == "林尘"
        assert merged.group_id == group_id
        assert merged.extra == {"tags": ["主角"]}
        assert merged.created_at == TS
        assert merged.is_deleted is False

    async def test_idempotent_second_extraction_produces_empty(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """幂等性: 同一文本二次提取 → created/updated/relations 全空，零写入。"""
        payload = _payload(
            chars=[
                {"name": "林尘", "personality": "坚韧", "background": "", "goals": ""},
                {"name": "苏瑶", "personality": "聪慧"},
            ],
            rels=[{"from": "林尘", "to": "苏瑶", "type": "同伴", "description": "结伴"}],
        )
        mock_llm.chat.return_value = _ok_response(payload)
        req = CharacterExtractRequest(project_id=PID, text="t")
        await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert mock_repo.add.await_count == 2
        assert mock_repo.add_relation.await_count == 1

        # 第二轮: 同名角色与同键关系均已存在且字段一致
        char1 = _char(name="林尘", personality="坚韧")
        char2 = _char(name="苏瑶", personality="聪慧")
        existing_rel = _rel(char1, char2, relation_type="同伴", description="结伴")
        by_name = {"林尘": char1, "苏瑶": char2}

        async def _get_by_name(pid: int, name: str) -> Character | None:
            return by_name.get(name)

        mock_repo.get_by_name = AsyncMock(side_effect=_get_by_name)
        mock_repo.get_relation_by_key = AsyncMock(return_value=existing_rel)

        result2 = await extractor.extract(req, default_model=DEFAULT_MODEL)
        assert result2.created == []
        assert result2.updated == []
        assert result2.relations_created == []
        assert result2.relations_updated == []
        assert mock_repo.add.await_count == 2  # 第二轮无新建
        assert mock_repo.add_relation.await_count == 1
        assert mock_repo.update.await_count == 0
        assert mock_repo.update_relation.await_count == 0

    async def test_soft_deleted_same_name_creates_new_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """软删除同名 → 新建角色 + warning（不隐式恢复旧档案）。"""
        deleted = _char(name="林尘", personality="旧档案", is_deleted=True)
        mock_repo.list = AsyncMock(return_value=([deleted], 1))
        mock_llm.chat.return_value = _ok_response(
            _payload(chars=[{"name": "林尘", "personality": "坚韧"}])
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].name == "林尘"
        assert result.created[0].is_deleted is False
        assert mock_repo.add.await_count == 1
        assert any("已删除" in w for w in result.warnings)

    async def test_invalid_entries_skipped_with_warning(
        self, extractor, mock_llm, mock_repo
    ) -> None:
        """非法条目（空名/超长名/空类型/超长类型）→ 跳过 + warning，其余正常落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                chars=[
                    {"name": ""},
                    {"name": "长" * 60},
                    {"name": "林尘", "personality": "坚韧"},
                    {"name": "苏瑶"},
                ],
                rels=[
                    {"from": "林尘", "to": "苏瑶", "type": "同伴"},
                    {"from": "林尘", "to": "苏瑶", "type": ""},
                    {"from": "林尘", "to": "苏瑶", "type": "师" * 30},
                ],
            )
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 2
        assert len(result.relations_created) == 1
        assert len(result.warnings) == 4  # 2 非法角色 + 2 非法关系

    async def test_unresolvable_relation_skipped(self, extractor, mock_llm, mock_repo) -> None:
        """关系引用不可解析名字 → 跳过 + warning，无悬空关系落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                chars=[{"name": "林尘"}],
                rels=[{"from": "林尘", "to": "不存在的人", "type": "相识"}],
            )
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.relations_created == []
        assert mock_repo.add_relation.await_count == 0
        assert any("无法解析" in w for w in result.warnings)

    async def test_fenced_output_extracts_json_fragment(self, extractor, mock_llm) -> None:
        """输出带围栏/前后缀文字 → _extract_json_fragment 提取成功。"""
        payload = _payload(chars=[{"name": "林尘"}])
        fenced = f"好的，以下是提取结果：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.created) == 1
        assert result.created[0].name == "林尘"

    async def test_invalid_output_retries_twice_then_raises(self, extractor, mock_llm) -> None:
        """输出完全非法 → 修复重试 2 次（共 3 次调用）→ CharacterExtractionError。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="这不是 JSON", model=DEFAULT_MODEL),
            ChatResponse(content="还是不对", model=DEFAULT_MODEL),
            ChatResponse(content="依然失败", model=DEFAULT_MODEL),
        ]
        with pytest.raises(CharacterExtractionError) as excinfo:
            await extractor.extract(
                CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 3
        assert excinfo.value.raw_output == "依然失败"
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(只输出 JSON)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "只输出 JSON" in call2_msgs[-1].content
        # 第 3 次调用保留完整对话历史
        call3_msgs = mock_llm.chat.await_args_list[2].args[0]
        assert call3_msgs[-2].content == "还是不对"

    async def test_llm_error_propagates_without_retry(self, extractor, mock_llm) -> None:
        """Mock LLM 抛 LLMRequestError → 透传，不消耗解析重试。"""
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await extractor.extract(
                CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 1

    async def test_llm_error_after_bad_output_propagates(self, extractor, mock_llm) -> None:
        """坏输出后 LLM 报错 → 立即透传，不进入第 3 次尝试。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="bad", model=DEFAULT_MODEL),
            LLMRequestError("timeout"),
        ]
        with pytest.raises(LLMRequestError):
            await extractor.extract(
                CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
            )
        assert mock_llm.chat.await_count == 2

    async def test_empty_characters_warns(self, extractor, mock_llm) -> None:
        """空角色列表 → 空结果 + warning。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.created == []
        assert result.updated == []
        assert result.relations_created == []
        assert len(result.warnings) == 1
        assert "未从文本中提取" in result.warnings[0]

    async def test_uses_template_default_model_and_temperature(
        self, extractor, mock_llm, mock_prompt_manager
    ) -> None:
        """断言使用 character_extract 模板 + 变量 text + 默认模型 + temperature 0.2。"""
        mock_llm.chat.return_value = _ok_response(_payload(chars=[{"name": "林尘"}]))
        await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="第一章文本"), default_model=DEFAULT_MODEL
        )
        mock_prompt_manager.load.assert_called_once_with("character_extract")
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(template, {"text": "第一章文本"})
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["temperature"] == 0.2
        msgs = mock_llm.chat.await_args.args[0]
        assert msgs[0].role == "system"
        assert msgs[-1].role == "user"

    async def test_request_model_overrides_default(self, extractor, mock_llm) -> None:
        """request.model 覆盖项目默认模型。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t", model="deepseek/deepseek-chat"),
            default_model=DEFAULT_MODEL,
        )
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"

    async def test_relation_key_update_and_idempotent(self, extractor, mock_llm, mock_repo) -> None:
        """同键关系已存在 → 更新 description（提取值非空时）；描述一致则幂等跳过。"""
        char1 = _char(name="林尘")
        char2 = _char(name="苏瑶")
        by_name = {"林尘": char1, "苏瑶": char2}

        async def _get_by_name(pid: int, name: str) -> Character | None:
            return by_name.get(name)

        mock_repo.get_by_name = AsyncMock(side_effect=_get_by_name)
        existing_rel = _rel(char1, char2, relation_type="同伴", description="旧描述")
        mock_repo.get_relation_by_key = AsyncMock(return_value=existing_rel)

        mock_llm.chat.return_value = _ok_response(
            _payload(rels=[{"from": "林尘", "to": "苏瑶", "type": "同伴", "description": "新描述"}])
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert len(result.relations_updated) == 1
        assert result.relations_updated[0].description == "新描述"
        assert mock_repo.update_relation.await_count == 1
        assert mock_repo.add_relation.await_count == 0

        # 幂等: 描述一致 → 不再更新（模拟 update 后仓储返回新描述）
        mock_repo.update_relation.reset_mock()
        mock_repo.get_relation_by_key = AsyncMock(
            return_value=_rel(char1, char2, relation_type="同伴", description="新描述")
        )
        mock_llm.chat.return_value = _ok_response(
            _payload(rels=[{"from": "林尘", "to": "苏瑶", "type": "同伴", "description": "新描述"}])
        )
        result2 = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result2.relations_updated == []
        assert result2.relations_created == []
        assert mock_repo.update_relation.await_count == 0

    async def test_self_loop_relation_skipped(self, extractor, mock_llm, mock_repo) -> None:
        """自环关系 → 跳过 + warning（对齐自环禁令）。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                chars=[{"name": "林尘"}],
                rels=[{"from": "林尘", "to": "林尘", "type": "自我"}],
            )
        )
        result = await extractor.extract(
            CharacterExtractRequest(project_id=PID, text="t"), default_model=DEFAULT_MODEL
        )
        assert result.relations_created == []
        assert mock_repo.add_relation.await_count == 0
        assert any("自环" in w for w in result.warnings)


class TestExtractJsonFragment:
    """_extract_json_fragment 纯函数测试。"""

    def test_balanced_nested_with_braces_in_string(self) -> None:
        """嵌套括号与字符串内花括号均正确处理。"""
        text = '前缀 {"a": {"b": [1, 2]}, "c": "}"} 后缀'
        assert _extract_json_fragment(text) == '{"a": {"b": [1, 2]}, "c": "}"}'

    def test_unbalanced_or_absent_returns_none(self) -> None:
        """无花括号或括号不平衡 → None。"""
        assert _extract_json_fragment("纯文本输出") is None
        assert _extract_json_fragment('{"a": 1') is None
