"""F13 伏笔管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：Foreshadowing 实体、Create/Update DTO（含 event_id 双语义：
None = 不修改，"" = 解除事件挂接）。
依据: specs/f13-foreshadowing/spec.md §2.5 + §9 测试策略「领域模型」。
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
FID = uuid.UUID("7a4c2e8f-0000-4000-8000-000000000001")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


class TestForeshadowingStatus:
    """ForeshadowingStatus 枚举测试（§2.4 状态机两值）."""

    def test_status_two_values(self):
        """枚举两值：OPEN='open' / RESOLVED='resolved'."""
        assert ForeshadowingStatus.OPEN == "open"
        assert ForeshadowingStatus.RESOLVED == "resolved"
        assert ForeshadowingStatus.OPEN.value == "open"
        assert ForeshadowingStatus.RESOLVED.value == "resolved"


class TestForeshadowingModel:
    """Foreshadowing 领域实体测试."""

    def test_entity_defaults(self):
        """默认值：description='', priority=50, status=OPEN, location='',
        event_id=None, resolved_at=None, extra={}."""
        foreshadowing = Foreshadowing(
            id=FID,
            project_id=PID,
            title="林尘的玉佩",
            created_at=TS,
            updated_at=TS,
        )
        assert foreshadowing.title == "林尘的玉佩"
        assert foreshadowing.description == ""
        assert foreshadowing.priority == 50
        assert foreshadowing.status == ForeshadowingStatus.OPEN
        assert foreshadowing.location == ""
        assert foreshadowing.event_id is None
        assert foreshadowing.resolved_at is None
        assert foreshadowing.extra == {}

    def test_entity_required_fields(self):
        """缺少必填字段（title）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Foreshadowing(
                id=FID,
                project_id=PID,
                created_at=TS,
                updated_at=TS,
            )

    def test_entity_accepts_event_id(self):
        """实体挂接事件锚点（event_id 合法 UUID）通过."""
        foreshadowing = Foreshadowing(
            id=FID,
            project_id=PID,
            title="伏笔",
            event_id=EID,
            created_at=TS,
            updated_at=TS,
        )
        assert foreshadowing.event_id == EID


class TestForeshadowingCreateValidation:
    """ForeshadowingCreate 请求 DTO 验证测试."""

    def test_create_valid_strips_title_and_defaults(self):
        """合法创建：title 去空白，priority 默认 50，event_id 默认 None."""
        create = ForeshadowingCreate(project_id=PID, title="  林尘的玉佩  ")
        assert create.title == "林尘的玉佩"
        assert create.description == ""
        assert create.priority == 50
        assert create.location == ""
        assert create.event_id is None

    def test_create_has_no_status_field(self):
        """Create DTO 无 status 字段（创建即 open，回收走 resolve 端点）."""
        assert "status" not in ForeshadowingCreate.model_fields

    def test_create_empty_or_whitespace_title_raises(self):
        """空/纯空白标题应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="伏笔名不能为空"):
            ForeshadowingCreate(project_id=PID, title="")
        with pytest.raises(ValidationError, match="伏笔名不能为空"):
            ForeshadowingCreate(project_id=PID, title="   ")

    def test_create_title_too_long_raises(self):
        """超过 100 字符的标题应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="伏笔名不能超过 100 个字符"):
            ForeshadowingCreate(project_id=PID, title="长" * 101)

    def test_create_description_too_long_raises(self):
        """超过 5000 字符的 description 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="伏笔描述不能超过 5000 个字符"):
            ForeshadowingCreate(project_id=PID, title="伏笔", description="文" * 5001)

    def test_create_priority_bounds(self):
        """priority 越界（-1/101）应抛出 ValidationError；边界（0/100）合法."""
        with pytest.raises(ValidationError, match="优先级必须在 0-100 之间"):
            ForeshadowingCreate(project_id=PID, title="伏笔", priority=-1)
        with pytest.raises(ValidationError, match="优先级必须在 0-100 之间"):
            ForeshadowingCreate(project_id=PID, title="伏笔", priority=101)
        assert ForeshadowingCreate(project_id=PID, title="伏笔", priority=0).priority == 0
        assert ForeshadowingCreate(project_id=PID, title="伏笔", priority=100).priority == 100

    def test_create_location_stripped_and_too_long_raises(self):
        """location 去空白保存（空串合法）；超过 200 字符应抛出 ValidationError."""
        create = ForeshadowingCreate(project_id=PID, title="伏笔", location=" 第 3 章 ")
        assert create.location == "第 3 章"
        with pytest.raises(ValidationError, match="埋设位置不能超过 200 个字符"):
            ForeshadowingCreate(project_id=PID, title="伏笔", location="位" * 201)

    def test_create_event_id_valid_and_invalid(self):
        """event_id 合法 UUID 与 None 合法；非法 UUID 格式应抛出 ValidationError."""
        assert ForeshadowingCreate(project_id=PID, title="伏笔", event_id=EID).event_id == EID
        assert ForeshadowingCreate(project_id=PID, title="伏笔", event_id=None).event_id is None
        with pytest.raises(ValidationError):
            ForeshadowingCreate(project_id=PID, title="伏笔", event_id="not-a-uuid")


class TestForeshadowingUpdate:
    """ForeshadowingUpdate 部分更新语义测试（exclude_unset，同 F1）."""

    def test_update_partial_semantics(self):
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = ForeshadowingUpdate(title="新标题")
        assert update.title == "新标题"
        assert update.description is None
        assert update.priority is None
        assert update.location is None
        assert update.event_id is None
        assert update.model_fields_set == {"title"}
        assert ForeshadowingUpdate().model_fields_set == set()

    def test_update_priority_none_means_no_change(self):
        """priority=None 表示不修改（None 进 model_fields_set，与不传可区分）."""
        none_update = ForeshadowingUpdate(priority=None)
        assert none_update.priority is None
        assert "priority" in none_update.model_fields_set

    def test_update_location_none_no_change_empty_clears(self):
        """location=None 不修改；\"\" 清除埋设位置（置为未记录）."""
        none_update = ForeshadowingUpdate(location=None)
        assert none_update.location is None
        assert "location" in none_update.model_fields_set
        clear_update = ForeshadowingUpdate(location="")
        assert clear_update.location == ""
        assert "location" in clear_update.model_fields_set

    def test_update_event_id_none_means_no_change(self):
        """event_id=None 表示不修改（None 进 model_fields_set）."""
        none_update = ForeshadowingUpdate(event_id=None)
        assert none_update.event_id is None
        assert "event_id" in none_update.model_fields_set

    def test_update_event_id_empty_means_clear(self):
        """event_id=\"\" 表示解除事件挂接（置为 None）."""
        clear_update = ForeshadowingUpdate(event_id="")
        assert clear_update.event_id == ""
        assert "event_id" in clear_update.model_fields_set

    def test_update_event_id_non_empty_str_raises(self):
        """event_id 传非空字符串应抛出 ValidationError（422 语义）."""
        with pytest.raises(ValidationError, match="解除事件挂接请传空字符串"):
            ForeshadowingUpdate(event_id="abc")

    def test_update_event_id_valid_uuid_passes(self):
        """event_id 传合法 UUID（或可解析的 UUID 字符串）通过."""
        update = ForeshadowingUpdate(event_id=EID)
        assert update.event_id == EID

    def test_update_has_no_status_resolved_at_fields(self):
        """Update DTO 无 status/resolved_at 字段（状态迁移走 resolve/reopen 端点）."""
        assert "status" not in ForeshadowingUpdate.model_fields
        assert "resolved_at" not in ForeshadowingUpdate.model_fields

    def test_update_title_empty_too_long_raises(self):
        """title 空/纯空白/超长应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="伏笔名不能为空"):
            ForeshadowingUpdate(title="")
        with pytest.raises(ValidationError, match="伏笔名不能为空"):
            ForeshadowingUpdate(title="  ")
        with pytest.raises(ValidationError, match="伏笔名不能超过 100 个字符"):
            ForeshadowingUpdate(title="长" * 101)

    def test_update_priority_bounds(self):
        """priority 越界应抛出 ValidationError；边界（0/100）合法."""
        with pytest.raises(ValidationError, match="优先级必须在 0-100 之间"):
            ForeshadowingUpdate(priority=-1)
        with pytest.raises(ValidationError, match="优先级必须在 0-100 之间"):
            ForeshadowingUpdate(priority=101)
        assert ForeshadowingUpdate(priority=0).priority == 0
        assert ForeshadowingUpdate(priority=100).priority == 100

    def test_update_location_too_long_raises(self):
        """location 超过 200 字符应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="埋设位置不能超过 200 个字符"):
            ForeshadowingUpdate(location="位" * 201)
