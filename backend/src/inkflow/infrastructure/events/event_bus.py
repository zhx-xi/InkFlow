"""进程内发布/订阅总线 — 数据面变更失效信号（#992 / ADR-053 D1，spec §15.2.2）。

契约来源
--------
- specs/f23-sse/spec.md §15.2.2（subscribe / publish / subscriber_count / 单例）、
  §15.5.3 E2-E3（丢弃最旧事件、无订阅者静默）、§15.4.2（生成器 aclose 注销）。

设计决策
--------
1. **尽力而为**：`publish` 非阻塞且**绝不抛异常**——事件是失效信号，不是事务保证；
   发布方（service 写路径）不因无订阅者 / 慢订阅者 / 队列满而受影响（ADR-053 影响节）。
2. **不背压发布方**：每个订阅者一条有界 `asyncio.Queue`，队列满 → **丢弃最旧事件**
   （GUI 失效信号可丢，下一次写入或轮询窗口会收敛；写入正确性不受影响）。
3. **订阅者生命周期**：`subscribe()` 返回异步生成器，**首次迭代时**注册队列，
   生成器被 `aclose` / 退栈时在 `finally` 中注销（断连无泄漏，§15.4.2）。
4. **单例作用域 = 进程内**（ADR-021 内核进程化）：GUI 经 HTTP/SSE 连接订阅，
   CLI / agent 在同一进程内直接发布。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from inkflow.domain.models.data_change_event import DataChangeEvent

logger = logging.getLogger(__name__)

#: 单订阅者队列容量（超出即丢弃最旧事件，spec §15.5.3 E2）
MAX_QUEUE_SIZE = 100


def _offer(queue: asyncio.Queue[DataChangeEvent], event: DataChangeEvent) -> None:
    """非阻塞投递；队列满则丢弃最旧事件后投递最新（绝不背压发布方）。"""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - 竞争兜底
            return


class EventBus:
    """进程内发布/订阅总线（ADR-053 D1）— asyncio.Queue per subscriber."""

    def __init__(self) -> None:
        """初始化空订阅者集合（订阅者随 subscribe() 生成器生命周期增删）。"""
        self._subscribers: set[asyncio.Queue[DataChangeEvent]] = set()

    def subscribe(self) -> AsyncGenerator[DataChangeEvent, None]:
        """注册订阅者，返回事件异步生成器；生成器被 aclose 时自动注销。

        注意：注册发生在**首次迭代**时（异步生成器体惰性执行）——订阅方需先
        开始消费（`async for` / `__anext__`），`subscriber_count` 才计入本订阅者。
        """

        async def _iterate() -> AsyncGenerator[DataChangeEvent, None]:
            queue: asyncio.Queue[DataChangeEvent] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
            self._subscribers.add(queue)
            try:
                while True:
                    yield await queue.get()
            finally:
                # 生成器被 aclose/退栈 → 注销订阅者（断连无泄漏，spec §15.4.2）
                self._subscribers.discard(queue)

        return _iterate()

    async def publish(self, event: DataChangeEvent) -> None:
        """广播事件给全部订阅者（尽力而为：慢订阅者不阻塞发布方，spec §15.5.3 E2）。

        无订阅者 → 静默丢弃（E3）；队列满 → 丢弃最旧事件；任何异常均被吞掉 +
        记 warning——**调用方（写路径）绝不因事件发布失败**。
        """
        try:
            for queue in list(self._subscribers):
                _offer(queue, event)
        except Exception as exc:  # 兜底：发布是尽力而为信号，绝不影响写路径
            logger.warning("事件广播失败（已忽略，不影响写路径）: %s", exc)

    @property
    def subscriber_count(self) -> int:
        """当前订阅者数（可观测性 + 测试断言锚点）。"""
        return len(self._subscribers)


#: 进程级总线实例（首次 get_event_bus() 时创建；测试通过替换本模块全局隔离）
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """返回进程级 EventBus 单例（API 层与 CLI/agent 同进程共享，ADR-021）。"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
