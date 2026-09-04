"""F11 大纲管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：Outline / PlotPoint / StoryArc 三实体、Create/Update DTO、
生成相关模型（GeneratedOutline / GeneratedPlotPoint / GeneratedArc、
OutlineGenerateRequest / OutlineGenerationResult）。
依据: specs/f11-outline/spec.md §2.5/§2.6 + §9 测试策略「领域模型」。
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineCreate,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    OutlineUpdate,
    PlotPoint,
    PlotPointCreate,
    PlotPointUpdate,
    StoryArc,
    StoryArcCreate,
    StoryArcUpdate,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OID = uuid.UUID("4a1b2c3d-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


class TestOutlineModel:
    """Outline 领域实体测试."""

    def test_outline_defaults(self):
        """默认值：description='', sort_order=0, extra={}."""
        outline = Outline(
            id=OID,
            project_id=PID,
            name="第一卷大纲",
            created_at=TS,
            updated_at=TS,
        )
        assert outline.name == "第一卷大纲"
        assert outline.description == ""
        assert outline.sort_order == 0
        assert outline.extra == {}

    def test_outline_required_fields(self):
        """缺少必填字段（name）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Outline(
                id=OID,
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestOutlineCreateValidation:
    """OutlineCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_name(self):
        """合法创建：name 去空白，description/sort_order 取默认值."""
        outline = OutlineCreate(project_id=PID, name="  第一卷大纲  ")
        assert outline.name == "第一卷大纲"
        assert outline.description == ""
        assert outline.sort_order == 0

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="大纲名不能为空"):
            OutlineCreate(project_id=PID, name="")

    def test_create_whitespace_name_raises(self):
        """纯空白名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="大纲名不能为空"):
            OutlineCreate(project_id=PID, name="   ")

    def test_create_name_too_long_raises(self):
        """超过 50 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="大纲名不能超过 50 个字符"):
            OutlineCreate(project_id=PID, name="长" * 51)

    def test_create_description_too_long_raises(self):
        """超过 5000 字符的 description 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="大纲描述不能超过 5000 个字符"):
            OutlineCreate(project_id=PID, name="第一卷大纲", description="文" * 5001)

    def test_create_negative_sort_order_raises(self):
        """负的 sort_order 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="排序权重不能为负数"):
            OutlineCreate(project_id=PID, name="第一卷大纲", sort_order=-1)

    def test_create_sort_order_zero_allowed(self):
        """sort_order=0（默认值）合法."""
        outline = OutlineCreate(project_id=PID, name="第一卷大纲", sort_order=0)
        assert outline.sort_order == 0


class TestOutlineUpdate:
    """OutlineUpdate 部分更新语义测试（exclude_unset，同 F1）."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = OutlineUpdate(name="新大纲名")
        assert update.name == "新大纲名"
        assert update.description is None
        assert update.sort_order is None
        assert update.model_fields_set == {"name"}

    def test_update_explicit_none_in_fields_set(self):
        """显式传 None 与不传可区分（None 进 model_fields_set）。"""
        none_update = OutlineUpdate(description=None)
        assert none_update.description is None
        assert "description" in none_update.model_fields_set
        assert OutlineUpdate().model_fields_set == set()

    def test_update_explicit_none_name_and_sort_order(self):
        """name/sort_order 显式传 None → validator None 分支直接返回。"""
        assert OutlineUpdate(name=None).name is None
        assert OutlineUpdate(sort_order=None).sort_order is None

    def test_update_negative_sort_order_raises(self):
        """负的 sort_order 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="排序权重不能为负数"):
            OutlineUpdate(sort_order=-1)


class TestPlotPointModel:
    """PlotPoint 领域实体测试."""

    def test_plot_point_defaults(self):
        """默认值：type='', position=0, arc_id=None, extra={}."""
        point = PlotPoint(
            id=OID,
            outline_id=OID,
            project_id=PID,
            name="主角获得金手指",
            created_at=TS,
            updated_at=TS,
        )
        assert point.type == ""
        assert point.description == ""
        assert point.position == 0
        assert point.arc_id is None
        assert point.extra == {}

    def test_plot_point_required_fields(self):
        """缺少必填字段（name）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            PlotPoint(
                id=OID,
                outline_id=OID,
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestPlotPointCreateValidation:
    """PlotPointCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_name(self):
        """合法创建：name 去空白，type/description 取默认值."""
        point = PlotPointCreate(outline_id=OID, name="  主角获得金手指  ")
        assert point.name == "主角获得金手指"
        assert point.type == ""
        assert point.description == ""
        assert point.position is None
        assert point.arc_id is None

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点名不能为空"):
            PlotPointCreate(outline_id=OID, name="")

    def test_create_whitespace_name_raises(self):
        """纯空白名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点名不能为空"):
            PlotPointCreate(outline_id=OID, name="  ")

    def test_create_name_too_long_raises(self):
        """超过 100 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点名不能超过 100 个字符"):
            PlotPointCreate(outline_id=OID, name="长" * 101)

    def test_create_type_empty_allowed_and_stripped(self):
        """type 空串合法（未分类），非空时去空白保存."""
        empty = PlotPointCreate(outline_id=OID, name="转折点", type="")
        assert empty.type == ""
        stripped = PlotPointCreate(outline_id=OID, name="转折点", type=" 高潮 ")
        assert stripped.type == "高潮"

    def test_create_type_too_long_raises(self):
        """超过 20 字符的 type 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点类型不能超过 20 个字符"):
            PlotPointCreate(outline_id=OID, name="转折点", type="类" * 21)

    def test_create_description_too_long_raises(self):
        """超过 5000 字符的 description 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点描述不能超过 5000 个字符"):
            PlotPointCreate(outline_id=OID, name="转折点", description="文" * 5001)

    def test_create_negative_position_raises(self):
        """负的 position 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="排序位置不能为负数"):
            PlotPointCreate(outline_id=OID, name="转折点", position=-1)

    def test_create_position_none_allowed(self):
        """position=None 合法（追加到大纲末尾，max+1 语义）."""
        point = PlotPointCreate(outline_id=OID, name="转折点", position=None)
        assert point.position is None


class TestPlotPointUpdate:
    """PlotPointUpdate 部分更新语义测试（arc_id 三态）."""

    def test_update_arc_id_none_vs_empty_clear(self):
        """arc_id: None 表示不修改，\"\" 表示清除弧线 — 与不传三者可区分."""
        absent = PlotPointUpdate(name="改名")
        assert "arc_id" not in absent.model_fields_set
        none_update = PlotPointUpdate(arc_id=None)
        assert none_update.arc_id is None
        assert "arc_id" in none_update.model_fields_set
        clear_update = PlotPointUpdate(arc_id="")
        assert clear_update.arc_id == ""
        assert "arc_id" in clear_update.model_fields_set

    def test_update_explicit_none_all_fields(self):
        """四个可选字段显式传 None → validator None 分支直接返回."""
        assert PlotPointUpdate(name=None).name is None
        assert PlotPointUpdate(type=None).type is None
        assert PlotPointUpdate(description=None).description is None
        assert PlotPointUpdate(position=None).position is None

    def test_update_non_none_values_validated(self):
        """非 None 值走共享校验：description 校验与 position 非负分支."""
        assert PlotPointUpdate(description="新描述").description == "新描述"
        assert PlotPointUpdate(position=3).position == 3

    def test_update_negative_position_raises(self):
        """负的 position 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="排序位置不能为负数"):
            PlotPointUpdate(position=-1)


class TestStoryArcModel:
    """StoryArc 领域实体测试."""

    def test_story_arc_defaults(self):
        """默认值：description=''."""
        arc = StoryArc(
            id=OID,
            project_id=PID,
            name="主角成长线",
            created_at=TS,
            updated_at=TS,
        )
        assert arc.name == "主角成长线"
        assert arc.description == ""

    def test_story_arc_required_fields(self):
        """缺少必填字段（name）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            StoryArc(
                id=OID,
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )


class TestStoryArcCreateValidation:
    """StoryArcCreate 请求 DTO 验证测试."""

    def test_create_valid_and_strips_name(self):
        """合法创建：name 去空白，description 取默认值."""
        arc = StoryArcCreate(project_id=PID, name="  主角成长线  ")
        assert arc.name == "主角成长线"
        assert arc.description == ""

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="弧线名不能为空"):
            StoryArcCreate(project_id=PID, name="")

    def test_create_whitespace_name_raises(self):
        """纯空白名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="弧线名不能为空"):
            StoryArcCreate(project_id=PID, name="  ")

    def test_create_name_too_long_raises(self):
        """超过 50 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="弧线名不能超过 50 个字符"):
            StoryArcCreate(project_id=PID, name="长" * 51)

    def test_create_description_too_long_raises(self):
        """超过 500 字符的 description 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="弧线说明不能超过 500 个字符"):
            StoryArcCreate(project_id=PID, name="主角成长线", description="文" * 501)


class TestStoryArcUpdate:
    """StoryArcUpdate 部分更新语义测试."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = StoryArcUpdate(name="新弧线名")
        assert update.name == "新弧线名"
        assert update.description is None
        assert update.model_fields_set == {"name"}
        assert StoryArcUpdate().model_fields_set == set()

    def test_update_explicit_none_fields(self):
        """name/description 显式传 None → validator None 分支直接返回."""
        assert StoryArcUpdate(name=None).name is None
        assert StoryArcUpdate(description=None).description is None


class TestOutlineGenerateRequest:
    """OutlineGenerateRequest 生成请求验证测试."""

    def test_generate_request_defaults(self):
        """默认值：name/prompt/num_chapters/model=None，save=True."""
        req = OutlineGenerateRequest(project_id=PID)
        assert req.project_id == PID
        assert req.name is None
        assert req.prompt is None
        assert req.num_chapters is None
        assert req.save is True
        assert req.model is None

    def test_generate_request_requires_project_id(self):
        """缺少必填字段（project_id）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            OutlineGenerateRequest()

    def test_generate_request_name_validation(self):
        """name 提供时须合法（去空白非空，≤ 50 字符）."""
        with pytest.raises(ValidationError, match="大纲名不能为空"):
            OutlineGenerateRequest(project_id=PID, name="   ")
        with pytest.raises(ValidationError, match="大纲名不能超过 50 个字符"):
            OutlineGenerateRequest(project_id=PID, name="长" * 51)

    def test_generate_request_num_chapters_out_of_range(self):
        """num_chapters 越界（<1 或 >100）应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="章节数不能小于 1"):
            OutlineGenerateRequest(project_id=PID, num_chapters=0)
        with pytest.raises(ValidationError, match="章节数不能超过 100"):
            OutlineGenerateRequest(project_id=PID, num_chapters=101)

    def test_generate_request_num_chapters_boundaries_allowed(self):
        """num_chapters=1 与 100 边界合法."""
        assert OutlineGenerateRequest(project_id=PID, num_chapters=1).num_chapters == 1
        assert OutlineGenerateRequest(project_id=PID, num_chapters=100).num_chapters == 100

    def test_generate_request_prompt_too_long_raises(self):
        """超过 20000 字符的 prompt 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="生成提示不能超过 20000 个字符"):
            OutlineGenerateRequest(project_id=PID, prompt="文" * 20001)

    def test_generate_request_save_false_allowed(self):
        """save=False 表示只预览不落库."""
        req = OutlineGenerateRequest(project_id=PID, save=False)
        assert req.save is False

    def test_generate_request_explicit_none_prompt(self):
        """prompt 显式传 None → validator None 分支直接返回."""
        assert OutlineGenerateRequest(project_id=PID, prompt=None).prompt is None

    def test_generate_request_explicit_none_name(self):
        """name 显式传 None → validator None 分支直接返回（缺省语义）。"""
        assert OutlineGenerateRequest(project_id=PID, name=None).name is None

    def test_generate_request_valid_name_uses_shared_validation(self):
        """name 非 None → 复用共享校验（去空白后返回）。"""
        req = OutlineGenerateRequest(project_id=PID, name="  第一卷规划  ")
        assert req.name == "第一卷规划"


class TestGeneratedModels:
    """LLM 生成结果 schema 校验测试（§2.6）."""

    def test_generated_arc_requires_name(self):
        """GeneratedArc 缺 name 应抛出 ValidationError；description 可空."""
        with pytest.raises(ValidationError):
            GeneratedArc()
        arc = GeneratedArc(name="主角成长线")
        assert arc.name == "主角成长线"
        assert arc.description is None

    def test_generated_arc_name_invalid_raises(self):
        """GeneratedArc name 空/超长应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="弧线名不能为空"):
            GeneratedArc(name="  ")
        with pytest.raises(ValidationError, match="弧线名不能超过 50 个字符"):
            GeneratedArc(name="长" * 51)

    def test_generated_plot_point_requires_name(self):
        """GeneratedPlotPoint 缺 name 应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            GeneratedPlotPoint()

    def test_generated_plot_point_arc_optional(self):
        """GeneratedPlotPoint 的 arc/type/description 均可空（arc=None = 不挂弧线）."""
        point = GeneratedPlotPoint(name="主角获得金手指")
        assert point.arc is None
        assert point.type is None
        assert point.description is None

    def test_generated_plot_point_name_invalid_raises(self):
        """GeneratedPlotPoint name 空/超长应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="情节点名不能为空"):
            GeneratedPlotPoint(name="")
        with pytest.raises(ValidationError, match="情节点名不能超过 100 个字符"):
            GeneratedPlotPoint(name="长" * 101)

    def test_generated_outline_defaults(self):
        """GeneratedOutline 缺省：name/description=None，arcs/plot_points 空列表（可空）."""
        outline = GeneratedOutline()
        assert outline.name is None
        assert outline.description is None
        assert outline.arcs == []
        assert outline.plot_points == []

    def test_generated_outline_description_too_long_raises(self):
        """GeneratedOutline description 超过 5000 字符应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="大纲描述不能超过 5000 个字符"):
            GeneratedOutline(description="文" * 5001)

    def test_generated_arc_explicit_none_description(self):
        """GeneratedArc description 显式传 None → validator None 分支直接返回."""
        assert GeneratedArc(name="主角成长线", description=None).description is None

    def test_generated_plot_point_explicit_none_fields(self):
        """GeneratedPlotPoint type/description 显式传 None → validator None 分支."""
        point = GeneratedPlotPoint(name="转折点", type=None, description=None)
        assert point.type is None
        assert point.description is None


class TestOutlineGenerationResult:
    """OutlineGenerationResult 生成结果测试."""

    def test_generation_result_saved_with_entities(self):
        """save=True：outline 为落库实体，preview 为 None，model 必填."""
        outline = Outline(
            id=OID,
            project_id=PID,
            name="第一卷大纲",
            created_at=TS,
            updated_at=TS,
        )
        result = OutlineGenerationResult(
            saved=True, outline=outline, model="deepseek/deepseek-chat"
        )
        assert result.saved is True
        assert result.outline == outline
        assert result.plot_points == []
        assert result.arcs == []
        assert result.preview is None
        assert result.warnings == []

    def test_generation_result_preview_mode(self):
        """save=False：preview 为生成的原始结构，outline 为 None."""
        preview = GeneratedOutline(name="第一卷大纲")
        result = OutlineGenerationResult(
            saved=False, preview=preview, model="deepseek/deepseek-chat"
        )
        assert result.outline is None
        assert result.preview == preview

    def test_generation_result_requires_model(self):
        """缺少必填字段（model）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            OutlineGenerationResult(saved=True)
