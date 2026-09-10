"""F23 §15 数据面变更事件信封 + 帧编码契约测试（spec §15.12.1 M1，批 A1）。

契约来源：specs/f23-sse/spec.md §15.2.1（DataChangeEvent 字段/默认值）、
§15.5.1（_encode_change_frame 帧编码）、§15.3.3（publish_change 发布形态）、
§15.2.4（source 判定链）、§15.9（traceparent 复用 #931）。

RED（首次提交）：inkflow.domain.models.data_change_event / inkflow.api.routers.events
/ inkflow.domain.services._data_change 三模块均不存在 → 收集期 ImportError → 全文
件 FAIL。GREEN：实现后本文件零改动转绿（测试是契约，实现不得改测试）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方用例）
════════════════════════════════════════════════════════════════════

1. `DataChangeEvent`（domain/models/data_change_event.py）= frozen dataclass，字段
   顺序/默认值严格照 §15.2.1：domain / op / resource_id / project_id=None /
   source="unknown" / entity_id=None / traceparent=None / occurred_at=None；
   domain 层零框架依赖（ADR-002/015）。
2. `_encode_change_frame(ev) -> str`（api/routers/events.py）逐行照 §15.5.1：
   `data: <json>\n\n`；`project_id is None` → **省略该键**（≠ null）；
   `entity_id` 恒等于 `resource_id`（兼容别名，ADR-053 v1.1）；`ensure_ascii=False`
   （CJK 不转义）；无 `done` 键、无 `id:`/`event:` 行（§15.5.1 不变量 2/4）。
3. `publish_change(domain, op, resource_id, project_id, *, source=None)`
   （domain/services/_data_change.py，§15.3.3 形态为 `async def` + 调用点 await）：
   resource_id / project_id 接受 object（UUID | int）→ 内部 str()；source 解析链
   「显式参数 > contextvar > "unknown"」；traceparent 复用 inkflow.logging.trace
   （无上下文 → None）；occurred_at = ISO-8601 UTC（ADR-055）；**绝不抛异常**
   （内部 try/except + warning，绝不阻断写路径）。
4. `set_event_source(source) -> Token` / `reset_event_source(token)`
   （同模块）：X-Inkflow-Source → contextvar 的写入口（§15.2.4 判定链；HTTP 中间件
   在批次 A3 落地，本批先提供可测的写入口，否则 contextvar 分支不可达）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from datetime import UTC, datetime

import pytest

from inkflow.api.routers.events import _encode_change_frame
from inkflow.domain.models.data_change_event import DataChangeEvent
from inkflow.domain.services._data_change import (
    publish_change,
    reset_event_source,
    set_event_source,
)
from inkflow.infrastructure.events import get_event_bus
from inkflow.logging.trace import (
    TraceContext,
    make_traceparent,
    reset_trace_context,
    set_trace_context,
)

PROJECT_ID = "3f2b9c14-7a5e-4d21-9f60-0c8ab1d47e33"


# ── M1：事件信封模型（§15.2.1） ────────────────────────────────────────


def test_minimal_event_defaults():
    """最小构造 → 可选字段取默认值（全局域 project_id=None，source="unknown"）。"""
    ev = DataChangeEvent(domain="map", op="create", resource_id="7")

    assert ev.domain == "map"
    assert ev.op == "create"
    assert ev.resource_id == "7"
    assert ev.project_id is None
    assert ev.source == "unknown"
    assert ev.entity_id is None
    assert ev.traceparent is None
    assert ev.occurred_at is None


def test_full_event_keeps_all_fields():
    """全字段构造 → 逐字段回显（值不被改写）。"""
    ev = DataChangeEvent(
        domain="chapter",
        op="update",
        resource_id="42",
        project_id=PROJECT_ID,
        source="cli",
        entity_id="42",
        traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        occurred_at="2026-09-10T12:00:01Z",
    )

    assert ev.domain == "chapter"
    assert ev.op == "update"
    assert ev.resource_id == "42"
    assert ev.project_id == PROJECT_ID
    assert ev.source == "cli"
    assert ev.entity_id == "42"
    assert ev.traceparent == "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    assert ev.occurred_at == "2026-09-10T12:00:01Z"


def test_event_is_frozen():
    """frozen dataclass：写字段 → FrozenInstanceError（事件发布后不可变）。"""
    ev = DataChangeEvent(domain="map", op="create", resource_id="7")

    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.op = "delete"  # type: ignore[misc]  # 反例：frozen 实例禁止赋值


def test_event_field_order_matches_spec():
    """字段声明顺序 = spec §15.2.1（位置参数调用契约）。"""
    assert [f.name for f in dataclasses.fields(DataChangeEvent)] == [
        "domain",
        "op",
        "resource_id",
        "project_id",
        "source",
        "entity_id",
        "traceparent",
        "occurred_at",
    ]


# ── M1：帧编码（§15.5.1） ─────────────────────────────────────────────


def _parse_frame(frame: str) -> tuple[str, dict]:
    """拆解 SSE 帧字符串 → (前缀行, JSON payload)。"""
    assert frame.endswith("\n\n"), "帧必须以空行结束（§15.5.1）"
    lines = frame[:-2].split("\n")
    assert len(lines) == 1, f"事件帧恰好一行 data:（§15.5.1 不变量 4）：{frame!r}"
    assert lines[0].startswith("data: "), f"帧前缀必须是 data: ：{frame!r}"
    return lines[0], json.loads(lines[0][len("data: ") :])


def test_encode_frame_omits_project_id_for_global_domain():
    """全局域事件（project_id=None）→ 帧省略 project_id 键（≠ null，§15.2.3）。"""
    ev = DataChangeEvent(
        domain="agent_template",
        op="update",
        resource_id="2",
        source="gui",
        occurred_at="2026-09-10T12:00:03Z",
    )

    _, payload = _parse_frame(_encode_change_frame(ev))

    assert "project_id" not in payload
    assert payload["domain"] == "agent_template"
    assert payload["op"] == "update"
    assert payload["resource_id"] == "2"
    assert payload["entity_id"] == "2"  # 兼容别名恒等于 resource_id（§15.2.1）
    assert payload["source"] == "gui"
    assert payload["occurred_at"] == "2026-09-10T12:00:03Z"
    assert "done" not in payload  # 事件帧无 done 字段（§15.5.1 不变量 2）
    assert "traceparent" not in payload  # 空值省略（§15.5.1）


def test_encode_frame_keeps_project_id_when_present():
    """反例：项目域事件（project_id 有值）→ 该键必须出现且值精确。"""
    ev = DataChangeEvent(
        domain="map",
        op="create",
        resource_id="7",
        project_id=PROJECT_ID,
        source="cli",
        traceparent="00-" + "c" * 32 + "-" + "d" * 16 + "-01",
    )

    _, payload = _parse_frame(_encode_change_frame(ev))

    assert payload["project_id"] == PROJECT_ID
    assert payload["traceparent"] == "00-" + "c" * 32 + "-" + "d" * 16 + "-01"


def test_encode_frame_falls_back_entity_id_to_resource_id():
    """entity_id 缺省 → 帧内 entity_id = resource_id（兼容别名）。"""
    ev = DataChangeEvent(domain="map", op="delete", resource_id="9")

    _, payload = _parse_frame(_encode_change_frame(ev))

    assert payload["entity_id"] == "9"
    assert payload["source"] == "unknown"  # 默认 source 非空 → 出现在帧中


def test_encode_frame_omits_blank_source():
    """空字符串 source（异常输入）→ 省略该键（§15.5.1 空值省略规则）。"""
    ev = DataChangeEvent(domain="map", op="create", resource_id="7", source="")

    _, payload = _parse_frame(_encode_change_frame(ev))

    assert "source" not in payload


def test_encode_frame_keeps_cjk_readable():
    """ensure_ascii=False：非 ASCII 原样输出（不转义为 \\uXXXX，§15.5.1）。

    当前信封字段均为标识符（ASCII）；本用例以非 ASCII 标识作**防御性**断言，
    锁定编码器的 ensure_ascii=False，避免未来信封新增文本字段时帧被转义。
    """
    ev = DataChangeEvent(domain="map", op="create", resource_id="草稿-中文标识")

    frame = _encode_change_frame(ev)

    assert "草稿-中文标识" in frame
    assert "\\u" not in frame
    _, payload = _parse_frame(frame)
    assert payload["resource_id"] == "草稿-中文标识"


def test_encode_frame_is_single_data_line():
    """帧形态 = `data: <json>` + 空行；无 id: / event: 行（§15.5.1 不变量 4）。"""
    frame = _encode_change_frame(DataChangeEvent(domain="map", op="create", resource_id="7"))

    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert "\n\n" not in frame[:-2]
    assert "id:" not in frame and "event:" not in frame


# ── §15.3.3：publish_change 统一辅助（A1 批交付的发布入口） ──────────────


class _RecordingBus:
    """记录型事件总线替身 —— 断言 publish_change 产出的信封字段。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.events: list[DataChangeEvent] = []
        self._error = error

    async def publish(self, event: DataChangeEvent) -> None:
        if self._error is not None:
            raise self._error
        self.events.append(event)


@pytest.fixture
def bus(monkeypatch) -> _RecordingBus:
    """替换进程级总线单例为记录型替身（本文件只测信封字段，不测投递）。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    recorder = _RecordingBus()
    monkeypatch.setattr(bus_module, "_event_bus", recorder)
    return recorder


@pytest.mark.asyncio
async def test_publish_change_str_converts_ids(bus):
    """UUID / int 主键 → 字符串（resource_id + project_id），别名同值。"""
    change_id = uuid.uuid4()

    await publish_change("map", "create", change_id, 7, source="cli")

    assert len(bus.events) == 1
    ev = bus.events[0]
    assert ev.domain == "map"
    assert ev.op == "create"
    assert ev.resource_id == str(change_id)
    assert ev.project_id == "7"
    assert ev.entity_id == str(change_id)  # 兼容别名恒等于 resource_id
    assert ev.source == "cli"


@pytest.mark.asyncio
async def test_publish_change_global_domain_project_id_none(bus):
    """全局域（无 project_id）→ 事件 project_id=None（不伪造 id，§15.2.3）。"""
    await publish_change("agent_template", "update", 2, None)

    assert bus.events[0].project_id is None


@pytest.mark.asyncio
async def test_publish_change_defaults_source_to_unknown(bus):
    """显式 source 缺省 + 无 contextvar → source="unknown"（§15.2.4 兜底）。"""
    await publish_change("map", "create", 7, None)

    assert bus.events[0].source == "unknown"


@pytest.mark.asyncio
async def test_publish_change_resolves_source_from_contextvar(bus):
    """contextvar 有标记（X-Inkflow-Source 中间件写入）→ 事件 source 取该值。"""
    token = set_event_source("cli")
    try:
        await publish_change("map", "create", 7, None)
    finally:
        reset_event_source(token)

    assert bus.events[0].source == "cli"


@pytest.mark.asyncio
async def test_publish_change_explicit_source_wins_over_contextvar(bus):
    """判定链「显式参数 > contextvar」：显式 source=mcp 覆盖 contextvar=cli。"""
    token = set_event_source("cli")
    try:
        await publish_change("map", "create", 7, None, source="mcp")
    finally:
        reset_event_source(token)

    assert bus.events[0].source == "mcp"


@pytest.mark.asyncio
async def test_publish_change_reuses_trace_context(bus):
    """HTTP 写路径（#931 中间件已建上下文）→ 信封携带该 traceparent（§15.9）。"""
    ctx = TraceContext(trace_id="a" * 32, span_id="b" * 16, parent_span_id="")
    token = set_trace_context(ctx)
    try:
        await publish_change("chapter", "create", 3, PROJECT_ID)
    finally:
        reset_trace_context(token)

    assert bus.events[0].traceparent == make_traceparent(ctx)


@pytest.mark.asyncio
async def test_publish_change_traceparent_none_without_context(bus):
    """CLI/agent 直连 service（无 trace 上下文）→ traceparent=None（§15.9 边界）。"""
    await publish_change("chapter", "create", 3, PROJECT_ID)

    assert bus.events[0].traceparent is None


@pytest.mark.asyncio
async def test_publish_change_occurred_at_is_utc_iso8601(bus):
    """occurred_at = ISO-8601 UTC `Z` 后缀（ADR-055：存储/传输一律 UTC）。"""
    before = datetime.now(UTC)

    await publish_change("map", "create", 7, None)

    occurred_at = bus.events[0].occurred_at
    assert occurred_at is not None
    assert occurred_at.endswith("Z")
    parsed = datetime.fromisoformat(occurred_at)
    assert parsed.tzinfo is not None
    assert before <= parsed <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_publish_change_swallows_bus_failure(monkeypatch):
    """总线抛异常 → publish_change 吞掉（写路径绝不因事件发布失败，§15.3.3）。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    monkeypatch.setattr(bus_module, "_event_bus", _RecordingBus(error=RuntimeError("bus down")))

    assert await publish_change("map", "create", 7, None) is None


@pytest.mark.asyncio
async def test_publish_change_swallows_bad_id(bus):
    """反例：resource_id 无法 str() → 仍不抛异常（事件是尽力而为信号）。"""

    class _Boom:
        def __str__(self) -> str:
            raise RuntimeError("cannot stringify")

    assert await publish_change("map", "create", _Boom(), None) is None
    assert bus.events == []


@pytest.mark.asyncio
async def test_publish_change_reaches_process_event_bus(monkeypatch):
    """真实总线路径：publish_change → 进程级单例 → 订阅者收到同一事件。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    monkeypatch.setattr(bus_module, "_event_bus", None)
    bus_instance = get_event_bus()
    agen = bus_instance.subscribe()
    try:
        pending = asyncio.create_task(agen.__anext__())
        for _ in range(50):  # 订阅注册在首次迭代后（异步生成器体惰性执行）
            if bus_instance.subscriber_count == 1:
                break
            await asyncio.sleep(0)
        await publish_change("map", "create", 7, None, source="cli")
        ev = await asyncio.wait_for(pending, 2)
    finally:
        await agen.aclose()

    assert ev.domain == "map"
    assert ev.source == "cli"
