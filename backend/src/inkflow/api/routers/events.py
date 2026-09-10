"""数据面变更事件订阅端点 — GET /api/v1/events/stream（#992 / ADR-053 D1）。

契约来源
--------
- specs/f23-sse/spec.md §15.4.1（端点 + 响应头 + project_id 过滤）、
  §15.5.1（事件帧 schema + 不变量）、§15.4.2（纯 ASGI + 断连清理）。

与 F23 §3-§6 写作流式端点的边界（spec §15 章首，勿混）
------------------------------------------------------
写作流（`POST /api/v1/writing/stream`）是**请求-响应式单向流**：一请求一链、随生成
结束关闭；本端点是**长驻订阅流**：GUI 挂载即订阅、跨请求持续接收其他客户端的写入。
两者共享 `data: <json>\\n\\n` 传输形态，但**帧 schema 不同**（§15.5.1 vs §6.2：
事件帧无 `done` 字段）、**生命周期不同**（§15.5.3 vs §5.3）——**解码器必须分开**。

硬约束（ADR-053 影响节 / spec §15.4.2）
--------------------------------------
1. **纯 ASGI**：本端点不得引入 `BaseHTTPMiddleware`（会缓冲/破坏 StreamingResponse）。
2. **断连清理**：订阅生成器被 `aclose` 时注销订阅者（无泄漏）；
   `asyncio.CancelledError` **不吞**、清理后原样冒泡（同 `chat_stream` 修过的坑）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from inkflow.domain.models.data_change_event import DataChangeEvent
from inkflow.infrastructure.events import get_event_bus
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1/events", tags=["事件"])


def _encode_change_frame(ev: DataChangeEvent) -> str:
    """DataChangeEvent → SSE 帧字符串（`data: <json>` + 空行，spec §15.5.1）。

    - `project_id is None`（全局域）→ **省略该键**（≠ null，§15.2.3）
    - `entity_id` 恒等于 `resource_id`（兼容别名，§15.2.1 v1.1）
    - 空值字段省略（source/traceparent/occurred_at）；`ensure_ascii=False` 保 CJK 可读
    """
    payload: dict[str, object] = {
        "domain": ev.domain,
        "op": ev.op,
        "resource_id": ev.resource_id,
        "entity_id": ev.entity_id or ev.resource_id,
    }
    if ev.project_id is not None:
        payload["project_id"] = ev.project_id
    if ev.source:
        payload["source"] = ev.source
    if ev.traceparent:
        payload["traceparent"] = ev.traceparent
    if ev.occurred_at:
        payload["occurred_at"] = ev.occurred_at
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _affects_project(ev: DataChangeEvent, project_id: str | None) -> bool:
    """订阅过滤（spec §15.4.1 / §15.6.3）：全局域事件恒通过，项目域仅匹配订阅项目。

    `project_id` 缺省 = 接收全部；事件 `project_id is None` 但**实际是项目域**
    （§15.3.2 已知例外）→ 通过（全项目刷新，有意的安全偏向）。
    """
    if project_id is None or ev.project_id is None:
        return True
    return ev.project_id == project_id


async def _event_frames(project_id: str | None) -> AsyncGenerator[str, None]:
    """订阅进程内总线 → SSE 帧流（长驻，spec §15.5.1 不变量 2：无终止帧）。

    生成器被 `aclose`（客户端断连 / 内核停止）时在 `finally` 中注销订阅者；
    `CancelledError` 不在此吞掉——原样冒泡由调用方（Starlette）处理（§15.4.2）。
    """
    events = get_event_bus().subscribe()
    try:
        async for ev in events:
            if not _affects_project(ev, project_id):
                continue
            yield _encode_change_frame(ev)
    finally:
        await events.aclose()


@router.get("/stream")
@instrument(caller_type="api")
async def stream_events(project_id: str | None = None) -> StreamingResponse:
    """订阅内核数据面变更事件（长驻 SSE，spec §15.4.1）。

    查询参数 `project_id`：只接收该项目的项目作用域事件 + 全部全局域事件；
    缺省 = 接收全部。
    """
    return StreamingResponse(
        _event_frames(project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 云端部署防代理缓冲（§15.4.1）
        },
    )
