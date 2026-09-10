"""F23 §15 事件订阅端点契约测试（#992 / ADR-053，批 A1，spec §15.12.1 M4/M5）。

契约来源：specs/f23-sse/spec.md §15.4.1（GET /api/v1/events/stream + 响应头 +
project_id 过滤）、§15.4.2（纯 ASGI + 断连清理 + CancelledError 不吞）、
§15.5.1（帧 schema）、§15.5.3 E3（无订阅者不阻断写入）。

════════════════════════════════════════════════════════════════════
为何不用 httpx ASGITransport（重要，勿"顺手统一"）
════════════════════════════════════════════════════════════════════

httpx 的 ASGITransport 是**非流式**实现：先 `await self.app(scope, receive, send)`
直到 app 返回，再交付缓冲好的响应体。本端点是**长驻订阅流**（§15.5.1 不变量 2：
无 done 帧、无终止帧）——用 aconnect_sse + ASGITransport 会永久挂起。

故本文件用极简 ASGI 探针直接驱动真实 app（`inkflow.api.app.app`）：消费
http.response.body 帧，达到预期帧数后向 receive 注入 http.disconnect，据此验证
真实中间件链 + 路由 + 断连清理（订阅者注销、无泄漏）。写作流的先例
（tests/api/test_writing_api.py 的 aconnect_sse）不适用于无终止帧的流。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方用例）
════════════════════════════════════════════════════════════════════

1. 路由：`router = APIRouter(prefix="/api/v1/events", tags=["事件"])`，
   `GET /api/v1/events/stream` → 200 + StreamingResponse
   （app.py 需 include_router；routers/__init__.py 需导出 events_router）。
2. 响应头（§15.4.1）：Content-Type: text/event-stream（charset 后缀允许）、
   Cache-Control: no-cache、Connection: keep-alive、X-Accel-Buffering: no。
3. 帧 schema（§15.5.1）：`data: <json>\n\n`；全局域事件省略 project_id 键；
   entity_id 恒等于 resource_id。
4. 过滤（§15.4.1）：`?project_id=<uuid>` → 仅该项目域事件 + 全部全局域事件。
5. 生命周期（§15.4.2）：客户端断连 → 订阅者注销（subscriber_count 归零）；
   取消信号（asyncio.CancelledError）不吞、清理后冒泡。
6. 无订阅者（§15.5.3 E3）：写入路径照常 200/201，publish 静默丢弃。
7. 无 token 模式：env `INKFLOW_SERVER_TOKEN` 未设置时 TokenAuthMiddleware 直通
   ——本文件用例级 delenv，免疫本机 shell 残留（test_settings_api.py 假设 #2 同款）。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers.events import _event_frames
from inkflow.domain.services._data_change import publish_change
from inkflow.infrastructure.events import get_event_bus

PROJECT_A = "3f2b9c14-7a5e-4d21-9f60-0c8ab1d47e33"
PROJECT_B = "aaaaaaaa-1111-2222-3333-444444444444"
STREAM_PATH = "/api/v1/events/stream"


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    """让步轮询等待条件成立（订阅注册在生成器首次迭代后才发生）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(0)


class AsgiStreamProbe:
    """极简 ASGI 探针 —— 驱动长驻 SSE 流、按需断开（替代非流式 ASGITransport）。"""

    def __init__(self, path: str, *, query: str = "") -> None:
        self._path = path
        self._query = query
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.frames: list[dict[str, object]] = []
        self.task: asyncio.Task[None] | None = None
        self._disconnected = asyncio.Event()
        self._request_sent = False
        self._enough_frames = asyncio.Event()
        self._expected_frames = 0
        self._buffer = ""

    async def _receive(self) -> dict[str, object]:
        """首个调用交付空请求体；其后挂起直到测试注入断连（长驻语义）。"""
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnected.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            self.status = int(message["status"])
            self.headers = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            self._consume(str(message.get("body", b""), "utf-8"))
        else:
            raise AssertionError(f"意外 ASGI 消息: {message['type']}")

    def _consume(self, chunk: str) -> None:
        self._buffer += chunk
        while "\n\n" in self._buffer:
            block, self._buffer = self._buffer.split("\n\n", 1)
            line = block.strip()
            assert line.startswith("data: "), f"非法 SSE 帧: {block!r}"
            self.frames.append(json.loads(line[len("data: ") :]))
        if len(self.frames) >= self._expected_frames:
            self._enough_frames.set()

    async def open(self) -> None:
        """启动 ASGI app（真实中间件链 + 路由）。"""
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self._path,
            "raw_path": self._path.encode("ascii"),
            "query_string": self._query.encode("ascii"),
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
        }
        self.task = asyncio.create_task(app(scope, self._receive, self._send))

    async def wait_frames(self, count: int, *, timeout: float = 3.0) -> None:
        """等待收到 N 帧（超时 → 断言失败并给出已收数量）。"""
        self._expected_frames = count
        if len(self.frames) >= count:
            self._enough_frames.set()
        try:
            await asyncio.wait_for(self._enough_frames.wait(), timeout)
        except TimeoutError as exc:
            raise AssertionError(
                f"等待 {count} 帧超时（已收 {len(self.frames)} 帧）"
            ) from exc

    async def disconnect(self, *, timeout: float = 3.0) -> None:
        """注入客户端断连并等待 app 收尾（Starlette 取消流任务 → 生成器 aclose）。"""
        self._disconnected.set()
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout)


@pytest.fixture(autouse=True)
def _no_server_token(monkeypatch):
    """无 token 模式（测试契约 #7）：免疫本机 INKFLOW_SERVER_TOKEN 残留。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _isolated_event_bus(monkeypatch):
    """每个用例独占 EventBus 单例（订阅者不跨用例泄漏）。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    monkeypatch.setattr(bus_module, "_event_bus", None)


# ── M4：订阅端点成功路径 ──────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_stream_delivers_frames_for_published_change():
    """订阅后触发一次写（publish_change）→ 客户端收到对应事件帧。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH)
    await probe.open()
    try:
        await _wait_for(lambda: bus.subscriber_count == 1)  # 订阅已注册再发布
        await publish_change("map", "create", 7, PROJECT_A, source="cli")
        await probe.wait_frames(1)

        assert probe.status == 200
        frame = probe.frames[0]
        assert frame["domain"] == "map"
        assert frame["op"] == "create"
        assert frame["resource_id"] == "7"
        assert frame["entity_id"] == "7"
        assert frame["project_id"] == PROJECT_A
        assert frame["source"] == "cli"
    finally:
        await probe.disconnect()


@pytest.mark.asyncio
@pytest.mark.api
async def test_stream_response_headers():
    """响应头严格照 §15.4.1（SSE 长驻流 + 云端防代理缓冲）。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH)
    await probe.open()
    try:
        await _wait_for(lambda: probe.status is not None)
        assert probe.status == 200
        assert probe.headers["content-type"].startswith("text/event-stream")
        assert probe.headers["cache-control"] == "no-cache"
        assert probe.headers["connection"] == "keep-alive"
        assert probe.headers["x-accel-buffering"] == "no"
        assert bus.subscriber_count == 1
    finally:
        await probe.disconnect()


@pytest.mark.asyncio
@pytest.mark.api
async def test_stream_frames_arrive_in_publish_order():
    """多事件顺序到达（同一订阅流内 FIFO，不重排）。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH)
    await probe.open()
    try:
        await _wait_for(lambda: bus.subscriber_count == 1)
        await publish_change("map", "create", 1, PROJECT_A, source="cli")
        await publish_change("map", "update", 1, PROJECT_A, source="cli")
        await publish_change("map", "delete", 1, PROJECT_A, source="cli")
        await probe.wait_frames(3)

        assert [f["op"] for f in probe.frames] == ["create", "update", "delete"]
        assert [f["resource_id"] for f in probe.frames] == ["1", "1", "1"]
    finally:
        await probe.disconnect()


@pytest.mark.asyncio
@pytest.mark.api
async def test_stream_project_filter_keeps_project_and_global_events():
    """§15.4.1 过滤：只推 `project_id=<A>` 的项目域事件 + 全部全局域事件。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH, query=f"project_id={PROJECT_A}")
    await probe.open()
    try:
        await _wait_for(lambda: bus.subscriber_count == 1)
        await publish_change("map", "create", 1, PROJECT_A, source="cli")
        await publish_change("map", "create", 2, PROJECT_B, source="cli")  # 被过滤
        await publish_change(
            "agent_template", "update", 3, None, source="gui"
        )  # 全局域
        await probe.wait_frames(2)

        assert [f["resource_id"] for f in probe.frames] == ["1", "3"]
        assert probe.frames[0]["project_id"] == PROJECT_A
        assert "project_id" not in probe.frames[1]  # 全局域省略该键（§15.2.3）
    finally:
        await probe.disconnect()


@pytest.mark.asyncio
@pytest.mark.api
async def test_stream_without_project_filter_keeps_all_events():
    """反例：缺省 project_id → 全量接收（含其他项目的事件）。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH)
    await probe.open()
    try:
        await _wait_for(lambda: bus.subscriber_count == 1)
        await publish_change("map", "create", 1, PROJECT_A, source="cli")
        await publish_change("map", "create", 2, PROJECT_B, source="cli")
        await probe.wait_frames(2)

        assert [f["resource_id"] for f in probe.frames] == ["1", "2"]
    finally:
        await probe.disconnect()


# ── M5：边界（断连清理 / 取消不吞 / 反例） ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_client_disconnect_unregisters_subscriber():
    """客户端断连 → 订阅者注销（subscriber_count 归零，无泄漏，§15.4.2）。"""
    bus = get_event_bus()
    probe = AsgiStreamProbe(STREAM_PATH)
    await probe.open()
    await _wait_for(lambda: bus.subscriber_count == 1)
    await publish_change("map", "create", 7, PROJECT_A, source="cli")
    await probe.wait_frames(1)
    assert bus.subscriber_count == 1

    await probe.disconnect()

    assert bus.subscriber_count == 0
    assert probe.task is not None and probe.task.done()


@pytest.mark.asyncio
@pytest.mark.api
async def test_cancelled_error_not_swallowed_by_frame_generator():
    """取消信号不吞、清理后冒泡（ADR-053 硬约束，§15.4.2）。

    直接驱动帧生成器：先取一帧（生成器停在 yield 处），再注入 CancelledError →
    必须原样冒泡（吞掉 = 内核无法正常取消长驻流），且订阅者已注销。
    """
    bus = get_event_bus()
    frames = _event_frames(None)
    pending = asyncio.create_task(frames.__anext__())
    try:
        await _wait_for(lambda: bus.subscriber_count == 1)
        await publish_change("map", "create", 7, PROJECT_A, source="cli")
        assert (await asyncio.wait_for(pending, 3)).startswith("data: ")

        with pytest.raises(asyncio.CancelledError):
            await frames.athrow(asyncio.CancelledError)

        assert bus.subscriber_count == 0
    finally:
        await frames.aclose()


@pytest.mark.asyncio
@pytest.mark.api
async def test_two_streams_are_independent_subscribers():
    """两条订阅流各自独立收全量事件（订阅者按连接计数）。"""
    bus = get_event_bus()
    first = AsgiStreamProbe(STREAM_PATH)
    second = AsgiStreamProbe(STREAM_PATH, query=f"project_id={PROJECT_A}")
    await first.open()
    await second.open()
    try:
        await _wait_for(lambda: bus.subscriber_count == 2)
        await publish_change("map", "create", 1, PROJECT_A, source="cli")
        await first.wait_frames(1)
        await second.wait_frames(1)

        assert first.frames[0]["resource_id"] == "1"
        assert second.frames[0]["resource_id"] == "1"
    finally:
        await first.disconnect()
        await second.disconnect()
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
@pytest.mark.api
async def test_write_endpoint_still_201_without_subscribers(override_get_db):
    """反例 §15.5.3 E3：无订阅者时写入路径照常成功，publish 静默丢弃。"""
    bus = get_event_bus()
    assert bus.subscriber_count == 0

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/projects",
            json={"name": f"无订阅写入-{uuid.uuid4().hex[:8]}", "tags": ["玄幻"]},
        )

    assert resp.status_code == 201
    assert bus.subscriber_count == 0
    assert await publish_change("map", "create", 7, None) is None  # 无订阅者：静默
    assert bus.subscriber_count == 0
