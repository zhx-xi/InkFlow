"""F23 §15 进程内 EventBus 契约测试（spec §15.12.1 M2，批 A1）。

契约来源：specs/f23-sse/spec.md §15.2.2（subscribe / publish / subscriber_count /
get_event_bus）、§15.5.3 E2/E3（丢弃最旧、无订阅者静默）、§15.4.2（aclose 注销）。

RED（首次提交）：inkflow.infrastructure.events 包不存在 → 收集期 ImportError →
全文件 FAIL。GREEN：实现后本文件零改动转绿。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方用例）
════════════════════════════════════════════════════════════════════

1. `subscribe() -> AsyncIterator[DataChangeEvent]` 返回**异步生成器**：注册发生在
   **首次迭代时**（异步生成器体惰性执行），生成器被 aclose / 退栈时在 finally
   自动注销——故本文件的用例先启动 `__anext__` 任务，再断言 subscriber_count。
2. `publish` **非阻塞、绝不抛异常**：无订阅者 → 静默丢弃；订阅者不消费（慢订阅者）
   → 不背压发布方；队列满 → **丢弃最旧事件**（容量 MAX_QUEUE_SIZE）；订阅者侧
   异常（消费方抛出）不影响 publish 返回。
3. `subscriber_count` property = 当前已注册订阅者数（可观测性 + 断言锚点）。
4. `get_event_bus()` 返回**进程级单例**（同一实例，ADR-021 同进程共享）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable

import pytest

import inkflow.infrastructure.events.event_bus as bus_module
from inkflow.domain.models.data_change_event import DataChangeEvent
from inkflow.infrastructure.events import EventBus, get_event_bus
from inkflow.infrastructure.events.event_bus import MAX_QUEUE_SIZE


async def _wait_for(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    """让步轮询等待条件成立（订阅注册在首次迭代后才发生，不能同步断言）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("等待订阅注册超时")
        await asyncio.sleep(0)


async def _start_subscription(
    bus: EventBus,
) -> tuple[AsyncGenerator[DataChangeEvent, None], asyncio.Task[DataChangeEvent]]:
    """订阅总线并等待注册完成 → (生成器, 待取首事件的 __anext__ 任务)。"""
    agen = bus.subscribe()
    pending = asyncio.create_task(agen.__anext__())
    await _wait_for(lambda: bus.subscriber_count >= 1)
    return agen, pending


def _event(resource_id: str, *, domain: str = "map", op: str = "create") -> DataChangeEvent:
    """构造测试事件（字段值即断言锚点）。"""
    return DataChangeEvent(domain=domain, op=op, resource_id=resource_id)


# ── 订阅 / 广播 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    """订阅后 publish → 订阅者收到同一事件对象（不改写、不拷贝）。"""
    bus = EventBus()
    agen, pending = await _start_subscription(bus)
    try:
        event = _event("7")
        await bus.publish(event)

        assert await asyncio.wait_for(pending, 2) is event
        assert bus.subscriber_count == 1
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_all_subscribers_receive_event():
    """多订阅者：一次 publish 广播给全部（各自独立队列）。"""
    bus = EventBus()
    first, first_pending = await _start_subscription(bus)
    second, second_pending = await _start_subscription(bus)
    await _wait_for(lambda: bus.subscriber_count == 2)
    try:
        event = _event("11", domain="character")
        await bus.publish(event)

        assert await asyncio.wait_for(first_pending, 2) is event
        assert await asyncio.wait_for(second_pending, 2) is event
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_publish_without_subscriber_is_silent():
    """§15.5.3 E3：无订阅者（纯 CLI 会话）→ publish 静默丢弃，不抛异常。"""
    bus = EventBus()

    assert await bus.publish(_event("7")) is None
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_publish_swallows_transport_failure():
    """兜底：投递环节抛出异常 → 被吞掉 + warning（发布绝不冒泡到写路径）。"""

    class _BrokenQueue:
        """故障订阅者队列替身：投递即抛（模拟传输层内部错误）。"""

        def put_nowait(self, event: DataChangeEvent) -> None:
            raise RuntimeError("transport down")

    bus = EventBus()
    bus._subscribers.add(_BrokenQueue())  # type: ignore[arg-type]  # 反例：故障传输替身

    assert await bus.publish(_event("7")) is None


@pytest.mark.asyncio
async def test_slow_subscriber_does_not_backpressure_publisher():
    """§15.5.3 E2：订阅者不消费 → 发布方不被阻塞（丢弃最旧，队列有上限）。"""
    bus = EventBus()
    agen, pending = await _start_subscription(bus)
    try:
        # 先取走 1 条：此后生成器停在 yield 处（慢订阅者，不再等待新事件）
        await bus.publish(_event("0"))
        assert (await asyncio.wait_for(pending, 2)).resource_id == "0"

        burst = MAX_QUEUE_SIZE * 2
        for i in range(1, burst):
            await bus.publish(_event(str(i)))

        assert bus.subscriber_count == 1  # 慢订阅者仍在线（未被踢出）
        # 队列只保留最新 MAX_QUEUE_SIZE 条（1..burst-1 中溢出部分被丢弃）
        head = await asyncio.wait_for(agen.__anext__(), 2)
        assert head.resource_id == str(burst - MAX_QUEUE_SIZE)
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_queue_full_drops_oldest_event():
    """队列满 → 丢弃最旧事件（保留最新，GUI 失效信号可丢、写入正确性不受影响）。"""
    bus = EventBus()
    agen, pending = await _start_subscription(bus)
    try:
        # 先取走 1 条：此后生成器停在 yield 处（慢订阅者，无待取 getter）
        await bus.publish(_event("1"))
        assert (await asyncio.wait_for(pending, 2)).resource_id == "1"

        total = MAX_QUEUE_SIZE + 4  # 队列容量 100 → 溢出 3 条
        for i in range(2, total + 1):
            await bus.publish(_event(str(i)))

        # 事件 2/3/4 被丢弃 → 首条为 5；最新事件必定保留
        assert (await asyncio.wait_for(agen.__anext__(), 2)).resource_id == "5"
        rest = [await asyncio.wait_for(agen.__anext__(), 2) for _ in range(MAX_QUEUE_SIZE - 1)]
        assert rest[-1].resource_id == str(total)
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_consumer_exception_does_not_break_publish():
    """订阅者侧异常（消费方抛出）→ publish 照常返回；其他订阅者照常收到事件。"""
    bus = EventBus()
    bad = bus.subscribe()
    good, good_pending = await _start_subscription(bus)

    async def _explode() -> None:
        async for _ev in bad:
            raise RuntimeError("订阅者处理异常")

    bad_task = asyncio.create_task(_explode())
    await _wait_for(lambda: bus.subscriber_count == 2)
    try:
        first = _event("1")
        await bus.publish(first)
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(bad_task, 2)

        assert await asyncio.wait_for(good_pending, 2) is first
        second = _event("2")
        await bus.publish(second)
        assert await asyncio.wait_for(good.__anext__(), 2) is second
    finally:
        await bad.aclose()
        await good.aclose()


# ── 注销 / 反例 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aclose_unregisters_subscriber():
    """生成器 aclose → 订阅者注销（subscriber_count 归零，无泄漏，§15.4.2）。"""
    bus = EventBus()
    agen, pending = await _start_subscription(bus)
    await bus.publish(_event("1"))
    assert (await asyncio.wait_for(pending, 2)).resource_id == "1"
    assert bus.subscriber_count == 1

    await agen.aclose()

    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_no_delivery_after_unsubscribe():
    """反例：注销后 publish 不再投递（生成器已关闭 → StopAsyncIteration）。"""
    bus = EventBus()
    agen, pending = await _start_subscription(bus)
    await bus.publish(_event("1"))
    assert (await asyncio.wait_for(pending, 2)).resource_id == "1"
    await agen.aclose()

    assert await bus.publish(_event("2")) is None  # 无订阅者：静默

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_unsubscribed_events_do_not_leak_across_subscriptions():
    """反例：注销旧订阅者后新建订阅者 → 只收到新事件（陈旧队列已释放）。"""
    bus = EventBus()
    first, first_pending = await _start_subscription(bus)
    await bus.publish(_event("1"))
    assert (await asyncio.wait_for(first_pending, 2)).resource_id == "1"
    await first.aclose()

    second, second_pending = await _start_subscription(bus)
    try:
        await bus.publish(_event("2"))

        assert (await asyncio.wait_for(second_pending, 2)).resource_id == "2"
        assert bus.subscriber_count == 1
    finally:
        await second.aclose()


# ── 单例 ──────────────────────────────────────────────────────────────


def test_get_event_bus_returns_process_singleton(monkeypatch):
    """get_event_bus() 进程级单例：多次调用返回同一实例（ADR-021 同进程共享）。"""
    monkeypatch.setattr(bus_module, "_event_bus", None)

    bus = get_event_bus()

    assert isinstance(bus, EventBus)
    assert get_event_bus() is bus
