"""F14 统一提取服务领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：ExtractionType / ExtractionStatus 枚举、ExtractionRequest 请求 DTO
（text 去空白/空/超 50000、text 与 chapter_ids 互斥、chapter_ids 空列表/超
100、num_chapters 1-100、auto_extract bool|None、type 非法值）、
ExtractionResult 信封默认值与 status 枚举、ExtractionRun 增量追踪记录、
ReindexResult 全量重建索引结果。
依据: specs/f14-extraction-service/spec.md §2.1/§2.2/§2.3/§2.5 + §9 测试策略「领域模型」。
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionResult,
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
    ReindexResult,
)
from inkflow.domain.ports.vector_store import EntityType

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


class TestExtractionTypeEnum:
    """ExtractionType 枚举（§2.1）— 7 种提取类型（#479 新增 KNOWLEDGE_RELATION）."""

    def test_seven_members(self):
        """枚举恰好包含 7 个成员（#479: 原 6 值 + KNOWLEDGE_RELATION，spec f48 §5.5.5）."""
        assert len(ExtractionType) == 7

    def test_member_values(self):
        """6 种类型的 value 与 spec §2.1 一一对应."""
        assert ExtractionType.CHARACTER.value == "character"
        assert ExtractionType.SETTING.value == "setting"
        assert ExtractionType.OUTLINE.value == "outline"
        assert ExtractionType.TIMELINE.value == "timeline"
        assert ExtractionType.FORESHADOWING.value == "foreshadowing"
        assert ExtractionType.STYLE.value == "style"

    def test_knowledge_relation_member(self):
        """#479 第 7 值: KNOWLEDGE_RELATION（extraction_runs 复用，spec f48 §5.5.5）."""
        assert ExtractionType.KNOWLEDGE_RELATION.value == "knowledge_relation"
        assert str(ExtractionType.KNOWLEDGE_RELATION) == "knowledge_relation"

    def test_str_equals_value(self):
        """StrEnum: str() 返回 value（可直接序列化为 API 字符串）."""
        assert str(ExtractionType.TIMELINE) == "timeline"

    def test_invalid_value_raises(self):
        """非法枚举值应抛出 ValueError."""
        with pytest.raises(ValueError):
            ExtractionType("character2")


class TestExtractionStatusEnum:
    """ExtractionStatus 枚举（§2.2）— success / skipped / error."""

    def test_three_members(self):
        """枚举恰好包含 3 个成员."""
        assert len(ExtractionStatus) == 3

    def test_member_values(self):
        """3 种状态的 value 与 spec §2.2 一一对应."""
        assert ExtractionStatus.SUCCESS.value == "success"
        assert ExtractionStatus.SKIPPED.value == "skipped"
        assert ExtractionStatus.ERROR.value == "error"


class TestExtractionRequestValidation:
    """ExtractionRequest 请求 DTO 校验（§2.2/§6.4 输入约束）."""

    def test_valid_minimal_defaults(self):
        """合法请求：type + text 提供，其余字段取默认值."""
        req = ExtractionRequest(
            project_id=PID, type=ExtractionType.CHARACTER, text="林尘觉醒了金手指。"
        )
        assert req.project_id == PID
        assert req.type == ExtractionType.CHARACTER
        assert req.text == "林尘觉醒了金手指。"
        assert req.chapter_ids is None
        assert req.prompt is None
        assert req.num_chapters is None
        assert req.save is True
        assert req.include_flashbacks is True
        assert req.auto_extract is None
        assert req.model is None
        assert req.index is False
        assert req.force is False

    def test_text_strips_whitespace(self):
        """text 去空白后保存（镜像 F9 约束）."""
        req = ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="  林尘觉醒  ")
        assert req.text == "林尘觉醒"

    def test_text_empty_raises(self):
        """空 text 应抛出 ValidationError（422 语义）."""
        with pytest.raises(ValidationError, match="章节文本不能为空"):
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="")

    def test_text_whitespace_only_raises(self):
        """纯空白 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="章节文本不能为空"):
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="   \t  ")

    def test_text_over_50000_raises(self):
        """超过 50000 字符的 text 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="章节文本不能超过 50000 个字符"):
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="文" * 50001)

    def test_text_exactly_50000_ok(self):
        """恰好 50000 字符的 text 合法（边界值）."""
        req = ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="文" * 50000)
        assert len(req.text) == 50000

    def test_chapter_ids_empty_list_raises(self):
        """空列表 chapter_ids 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="chapter_ids 不能为空列表"):
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, chapter_ids=[])

    def test_chapter_ids_over_100_raises(self):
        """超过 100 章的 chapter_ids 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="单次提取章节数不能超过 100"):
            ExtractionRequest(
                project_id=PID,
                type=ExtractionType.CHARACTER,
                chapter_ids=[uuid.uuid4() for _ in range(101)],
            )

    def test_chapter_ids_exactly_100_ok(self):
        """恰好 100 章的 chapter_ids 合法（边界值）."""
        req = ExtractionRequest(
            project_id=PID,
            type=ExtractionType.CHARACTER,
            chapter_ids=[uuid.uuid4() for _ in range(100)],
        )
        assert len(req.chapter_ids) == 100

    def test_text_and_chapter_ids_mutually_exclusive(self):
        """text 与 chapter_ids 同时提供应抛出 ValidationError（§7 互斥）."""
        with pytest.raises(ValidationError, match="text 与 chapter_ids 不能同时使用"):
            ExtractionRequest(
                project_id=PID, type=ExtractionType.CHARACTER, text="内容", chapter_ids=[CID]
            )

    def test_num_chapters_zero_raises(self):
        """num_chapters=0 应抛出 ValidationError（outline 场景）."""
        with pytest.raises(ValidationError, match="num_chapters 必须在 1-100 之间"):
            ExtractionRequest(project_id=PID, type=ExtractionType.OUTLINE, num_chapters=0)

    def test_num_chapters_over_100_raises(self):
        """num_chapters=101 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="num_chapters 必须在 1-100 之间"):
            ExtractionRequest(project_id=PID, type=ExtractionType.OUTLINE, num_chapters=101)

    def test_num_chapters_boundaries_ok(self):
        """num_chapters=1 与 100 均合法（边界值）."""
        req1 = ExtractionRequest(project_id=PID, type=ExtractionType.OUTLINE, num_chapters=1)
        req100 = ExtractionRequest(project_id=PID, type=ExtractionType.OUTLINE, num_chapters=100)
        assert req1.num_chapters == 1
        assert req100.num_chapters == 100

    def test_auto_extract_accepts_bool_and_none(self):
        """auto_extract 接受 True/False/None（timeline 设置项覆盖，§2.6）."""
        t_true = ExtractionRequest(project_id=PID, type=ExtractionType.TIMELINE, auto_extract=True)
        t_false = ExtractionRequest(
            project_id=PID, type=ExtractionType.TIMELINE, auto_extract=False
        )
        t_none = ExtractionRequest(project_id=PID, type=ExtractionType.TIMELINE, auto_extract=None)
        assert t_true.auto_extract is True
        assert t_false.auto_extract is False
        assert t_none.auto_extract is None

    def test_auto_extract_invalid_type_raises(self):
        """auto_extract 传入非 bool 值应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionRequest(project_id=PID, type=ExtractionType.TIMELINE, auto_extract="maybe")

    def test_type_invalid_value_raises(self):
        """type 传入非 6 种枚举值应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionRequest(project_id=PID, type="character2", text="内容")

    def test_invalid_project_id_raises(self):
        """project_id 传入非法 UUID 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionRequest(project_id="not-a-uuid", type=ExtractionType.CHARACTER, text="内容")


class TestExtractionResultModel:
    """ExtractionResult 统一提取结果信封（§2.2/§5.3）."""

    def test_defaults(self):
        """默认值：skipped_reason=None、各计数 0、warnings=[]、model=None、
        indexed=False、detail={}."""
        result = ExtractionResult(type=ExtractionType.CHARACTER, status=ExtractionStatus.SUCCESS)
        assert result.type == ExtractionType.CHARACTER
        assert result.status == ExtractionStatus.SUCCESS
        assert result.skipped_reason is None
        assert result.processed_sources == 0
        assert result.skipped_sources == 0
        assert result.created == 0
        assert result.updated == 0
        assert result.warnings == []
        assert result.model is None
        assert result.indexed is False
        assert result.detail == {}

    def test_status_enum_coercion(self):
        """status 接受字符串字面量（自动转枚举）与枚举值."""
        assert (
            ExtractionResult(type=ExtractionType.SETTING, status="skipped").status
            == ExtractionStatus.SKIPPED
        )
        assert (
            ExtractionResult(type=ExtractionType.SETTING, status=ExtractionStatus.ERROR).status
            == ExtractionStatus.ERROR
        )

    def test_invalid_status_raises(self):
        """status 传入非 success/skipped/error 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionResult(type=ExtractionType.CHARACTER, status="failed")

    def test_missing_type_raises(self):
        """缺少必填 type 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionResult(status=ExtractionStatus.SUCCESS)

    def test_default_lists_are_independent(self):
        """warnings/detail 默认值为每实例独立（default_factory，非共享可变默认）."""
        a = ExtractionResult(type=ExtractionType.CHARACTER, status=ExtractionStatus.SUCCESS)
        b = ExtractionResult(type=ExtractionType.CHARACTER, status=ExtractionStatus.SUCCESS)
        a.warnings.append("x")
        a.detail["k"] = 1
        assert b.warnings == []
        assert b.detail == {}


class TestExtractionRunModel:
    """ExtractionRun 增量追踪记录（§2.3）— 每 (project, type, source) 一行最新状态."""

    def test_required_fields_and_defaults(self):
        """必填字段 + 默认值：status=SUCCESS、各计数 0、warnings_json="[]"、
        error=None、model=None、indexed=False."""
        run = ExtractionRun(
            id=1,
            project_id=PID,
            type=ExtractionType.CHARACTER,
            source_key="manual",
            content_hash="abc123",
            run_at=TS,
        )
        assert run.id == 1
        assert run.project_id == PID
        assert run.type == ExtractionType.CHARACTER
        assert run.source_key == "manual"
        assert run.content_hash == "abc123"
        assert run.status == ExtractionStatus.SUCCESS
        assert run.created_count == 0
        assert run.updated_count == 0
        assert run.warnings_json == "[]"
        assert run.error is None
        assert run.model is None
        assert run.indexed is False
        assert run.run_at == TS

    def test_missing_required_field_raises(self):
        """缺少必填 content_hash 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ExtractionRun(
                id=1,
                project_id=PID,
                type=ExtractionType.CHARACTER,
                source_key="manual",
                run_at=TS,
            )

    def test_error_status_fields_roundtrip(self):
        """status=error 场景：错误消息/计数/indexed 字段可完整表达."""
        run = ExtractionRun(
            id=2,
            project_id=PID,
            type=ExtractionType.CHARACTER,
            source_key="manual",
            content_hash="abc123",
            status=ExtractionStatus.ERROR,
            created_count=1,
            updated_count=2,
            warnings_json='["解析跳过"]',
            error="LLM 调用失败",
            model="gpt-4o",
            indexed=True,
            run_at=TS,
        )
        assert run.status == ExtractionStatus.ERROR
        assert run.created_count == 1
        assert run.updated_count == 2
        assert run.error == "LLM 调用失败"
        assert run.indexed is True

    def test_from_attributes(self):
        """model_config from_attributes：可由 ORM 行对象直接构造（§2.3）."""

        class _RunRow:
            id = 3
            project_id = PID
            type = ExtractionType.FORESHADOWING
            source_key = "manual"
            content_hash = "def456"
            status = ExtractionStatus.SKIPPED
            created_count = 0
            updated_count = 0
            warnings_json = "[]"
            error = None
            model = None
            indexed = False
            run_at = TS

        run = ExtractionRun.model_validate(_RunRow())
        assert run.id == 3
        assert run.type == ExtractionType.FORESHADOWING
        assert run.status == ExtractionStatus.SKIPPED


class TestReindexResultModel:
    """ReindexResult 全量重建索引结果（§2.2/§5.6）."""

    def test_required_fields_and_defaults(self):
        """必填字段 + warnings 默认 []."""
        result = ReindexResult(
            project_id=PID,
            entity_types=[EntityType.CHARACTER, EntityType.SETTING],
            indexed=42,
        )
        assert result.project_id == PID
        assert result.entity_types == [EntityType.CHARACTER, EntityType.SETTING]
        assert result.indexed == 42
        assert result.warnings == []

    def test_missing_indexed_raises(self):
        """缺少必填 indexed 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ReindexResult(project_id=PID, entity_types=[EntityType.CHARACTER])

    def test_invalid_entity_type_raises(self):
        """entity_types 传入非 EntityType 枚举值应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            ReindexResult(project_id=PID, entity_types=["invalid"], indexed=1)
