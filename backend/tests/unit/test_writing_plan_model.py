"""F44 阶段1+2 WritingPlan 模型 + 多维上限单测（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §2.1/§2.4（v1.1）。
本文件为 `domain/models/writing_plan.py`（NEW）定义契约：WritingPlan 实体、
PlanNodeStatus 状态机、BookLimits 上限模型、validate_at_least_one_hard_limit
「至少一道有限护栏」不变式、阶段1 写死上限常量、阶段2 merge_book_limits
纯函数（Q2=C：ProjectConfig.extra 项目级上限合并，§2.4/D11）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【模块契约】`inkflow.domain.models.writing_plan` 必须暴露：
   - `PlanNodeStatus(StrEnum)`：PENDING="pending" / IN_PROGRESS="in_progress" /
     DONE="done" / FAILED="failed" / SKIPPED="skipped"（§2.1 进度状态机）
   - `WritingPlan(BaseModel)`（§2.1 字段全集，model_config from_attributes）：
       id: uuid.UUID
       project_id: uuid.UUID
       title: str
       status: str = "drafting"        # drafting/auto/ready/running/completed/aborted
       root_outline_id: uuid.UUID | None = None
       character_ids: list[uuid.UUID] = []
       limits: dict[str, int] = {}
       progress: dict[str, str] = {}   # outline_id -> PlanNodeStatus value
       execution_refs: dict[str, str] = {}  # outline_id -> execution_id
       thread_id: str | None = None
       created_at: datetime = utcnow
       updated_at: datetime = utcnow
     （limits/progress/execution_refs 恒为可变默认——default_factory，不共享实例）
   - `BookLimits(BaseModel)`（§2.4 默认常量）：
       max_chapters: int = 100
       max_agent_calls: int = 200
       max_tokens: int = 200_000      # 软护栏
       max_sessions: int = 5
   - `validate_at_least_one_hard_limit(limits: BookLimits) -> None`：
     max_chapters/max_agent_calls 至少一个有限值（>0）；全 0/None → ValueError
     （消息含「至少一道」或等价中文语义）；合法 → 无返回值
   - `STAGE1_LIMITS: BookLimits`（#335 上限写死但计数器立起来）：
     max_chapters=1 / max_agent_calls=1（其余取默认）

2. 【阶段 2 契约：merge_book_limits 纯函数】（模块级，§2.4/D11 读取优先级
   请求显式 > 项目级 extra > 默认常量；Q2=C 拍板 v1.1）：
   逐字签名：
       merge_book_limits(request_limits: BookLimits | None,
                         project_extra: dict[str, Any] | None = None) -> BookLimits
   合并链：
   a. 起点 = 默认 BookLimits()（100/200/200000/5）
   b. project_extra 键 book_max_chapters / book_max_agent_calls /
      book_max_tokens / book_max_sessions 覆盖（值 int 转换；缺键跳过）
   c. request_limits 显式字段覆盖（request.model_fields_set 只覆盖显式键，
      未显式字段回退项目级/默认）
   纯函数：不修改入参、无副作用、无 IO。

3. 【RED 预期形态】merge_book_limits 在阶段 1 实现中不存在 → 本文件 merge
   用例 AttributeError/ImportError 失败；既有用例（阶段 1 已满足）PASS 守护。

4. 【时间戳】created_at/updated_at 为 datetime（UTC），GREEN 用
   `datetime.now(timezone.utc)` 等价实现。
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from inkflow.domain.models.writing_plan import (
    STAGE1_LIMITS,
    BookLimits,
    PlanNodeStatus,
    WritingPlan,
    validate_at_least_one_hard_limit,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── PlanNodeStatus ────────────────────────────────────────────────


def test_plan_node_status_enum_values():
    """PlanNodeStatus 五个进度值契约（§2.1）。"""
    assert PlanNodeStatus.PENDING.value == "pending"
    assert PlanNodeStatus.IN_PROGRESS.value == "in_progress"
    assert PlanNodeStatus.DONE.value == "done"
    assert PlanNodeStatus.FAILED.value == "failed"
    assert PlanNodeStatus.SKIPPED.value == "skipped"


def test_plan_node_status_is_strenum():
    """PlanNodeStatus 须为 StrEnum（仓库枚举惯例，UP042）。"""
    assert issubclass(PlanNodeStatus, str)


# ── WritingPlan ───────────────────────────────────────────────────


def test_writing_plan_defaults():
    """WritingPlan 默认字段契约（§2.1）：status=drafting、可变集合用 factory。"""
    plan = WritingPlan(id=uuid4(), project_id=uuid4(), title="测试计划")
    assert plan.status == "drafting"
    assert plan.root_outline_id is None
    assert plan.character_ids == []
    assert plan.limits == {}
    assert plan.progress == {}
    assert plan.execution_refs == {}
    assert plan.thread_id is None
    assert isinstance(plan.created_at, datetime)
    assert isinstance(plan.updated_at, datetime)


def test_writing_plan_mutable_defaults_not_shared():
    """可变默认值不共享实例（default_factory）——一个实例修改不影响另一个。"""
    a = WritingPlan(id=uuid4(), project_id=uuid4(), title="A")
    b = WritingPlan(id=uuid4(), project_id=uuid4(), title="B")
    a.progress["outline-1"] = "done"
    assert b.progress == {}


def test_writing_plan_from_attributes():
    """model_config from_attributes——ORM 对象可直构（§2.1）。"""
    from typing import ClassVar

    class _Row:
        id = uuid4()
        project_id = uuid4()
        title = "ORM 计划"
        status = "ready"
        root_outline_id = None
        character_ids: ClassVar[list] = []
        limits: ClassVar[dict] = {}
        progress: ClassVar[dict] = {}
        execution_refs: ClassVar[dict] = {}
        thread_id = None
        created_at = _utcnow()
        updated_at = _utcnow()

    plan = WritingPlan.model_validate(_Row())
    assert plan.title == "ORM 计划"
    assert plan.status == "ready"


def test_writing_plan_status_accepts_auto():
    """status 字符串字段：auto 是「全部你决定」路径的合法值（§5.1）。"""
    plan = WritingPlan(id=uuid4(), project_id=uuid4(), title="auto 计划", status="auto")
    assert plan.status == "auto"


# ── BookLimits ────────────────────────────────────────────────────


def test_book_limits_defaults():
    """BookLimits 默认常量（§2.4）：100/200/200000/5。"""
    limits = BookLimits()
    assert limits.max_chapters == 100
    assert limits.max_agent_calls == 200
    assert limits.max_tokens == 200_000
    assert limits.max_sessions == 5


def test_book_limits_custom():
    """BookLimits 可传自定义值。"""
    limits = BookLimits(max_chapters=5, max_agent_calls=10, max_tokens=50_000, max_sessions=3)
    assert limits.max_chapters == 5
    assert limits.max_agent_calls == 10


# ── validate_at_least_one_hard_limit ──────────────────────────────


def test_validate_all_zero_raises():
    """全无上限（max_chapters=0 且 max_agent_calls=0）→ ValueError（§2.4 不变式）。"""
    with pytest.raises(ValueError):
        validate_at_least_one_hard_limit(BookLimits(max_chapters=0, max_agent_calls=0))


def test_validate_one_hard_limit_ok():
    """至少一道有限护栏：max_chapters=0 但 max_agent_calls=5 → 通过（spec §9.2 场景 2）。"""
    validate_at_least_one_hard_limit(BookLimits(max_chapters=0, max_agent_calls=5))


def test_validate_defaults_ok():
    """默认 BookLimits（100/200）天然通过。"""
    validate_at_least_one_hard_limit(BookLimits())


# ── STAGE1_LIMITS ─────────────────────────────────────────────────


def test_stage1_limits_hardcoded():
    """阶段1 上限写死：max_chapters=1 / max_agent_calls=1（#335），且通过护栏校验。"""
    assert STAGE1_LIMITS.max_chapters == 1
    assert STAGE1_LIMITS.max_agent_calls == 1
    validate_at_least_one_hard_limit(STAGE1_LIMITS)


# ── merge_book_limits（阶段 2：#336 Q2=C 读取优先级 请求显式 > 项目级 > 默认）──


def _merge(request_limits, project_extra=None):
    """阶段 2 契约：merge_book_limits 模块级纯函数。

    阶段 1 实现不存在该函数 → 属性访问 AttributeError → 本组用例 RED。
    """
    import inkflow.domain.models.writing_plan as _wp

    return _wp.merge_book_limits(request_limits, project_extra)


def test_merge_book_limits_all_defaults():
    """全空（无请求无项目级）→ BookLimits() 默认：100/200/200000/5（§2.4）。"""
    merged = _merge(None)
    assert merged.max_chapters == 100
    assert merged.max_agent_calls == 200
    assert merged.max_tokens == 200_000
    assert merged.max_sessions == 5


def test_merge_book_limits_project_extra_only():
    """仅项目级 extra：book_max_chapters/book_max_tokens 覆盖，其余字段回退默认（§2.4/D11）。"""
    merged = _merge(None, {"book_max_chapters": 3, "book_max_tokens": 50_000})
    assert merged.max_chapters == 3
    assert merged.max_tokens == 50_000
    assert merged.max_agent_calls == 200
    assert merged.max_sessions == 5


def test_merge_book_limits_request_overrides_project():
    """请求显式 > 项目级：extra book_max_chapters=2 + 请求 BookLimits(max_chapters=5)
    → 5（§2.4 读取优先级）。"""
    merged = _merge(BookLimits(max_chapters=5), {"book_max_chapters": 2})
    assert merged.max_chapters == 5
    assert merged.max_agent_calls == 200


def test_merge_book_limits_request_partial_fallback():
    """请求只显式 max_chapters → 其余字段回退项目级/默认（model_fields_set 语义）。"""
    merged = _merge(
        BookLimits(max_chapters=5),
        {"book_max_agent_calls": 7, "book_max_tokens": 50_000},
    )
    assert merged.max_chapters == 5
    assert merged.max_agent_calls == 7
    assert merged.max_tokens == 50_000
    assert merged.max_sessions == 5


def test_merge_book_limits_extra_string_int_coercion():
    """project_extra 值非 int（字符串 "3"）→ int 转换后生效。"""
    merged = _merge(None, {"book_max_chapters": "3"})
    assert merged.max_chapters == 3
