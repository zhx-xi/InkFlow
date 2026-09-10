"""domain/services 单元测试共享 fixture（#1088 批 A3）。

批 A3 在 8 个域的 service 写路径末尾接入 `publish_change`（spec §15.3.3）——
各域测试需断言「写成功 → 恰好一条事件（domain/op/resource_id/project_id 正确）」
与反例「写失败 / 返回 None / 返回 False → 零事件」。

`recorded_events` 以记录型总线替身替换进程级单例（同
tests/unit/test_data_change_event.py 的 `bus` fixture 手法），避免用例间订阅者泄漏。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from inkflow.domain.models.data_change_event import DataChangeEvent


class RecordingEventBus:
    """记录型事件总线替身 —— publish 只记录事件（异步签名与真实 EventBus 一致）。"""

    def __init__(self) -> None:
        self.events: list[DataChangeEvent] = []

    async def publish(self, event: DataChangeEvent) -> None:
        self.events.append(event)


@pytest.fixture
def recorded_events(monkeypatch) -> list[DataChangeEvent]:
    """替换进程级总线单例 → 返回本次用例收到的 DataChangeEvent 列表。"""
    import inkflow.infrastructure.events.event_bus as bus_module

    recorder = RecordingEventBus()
    monkeypatch.setattr(bus_module, "_event_bus", recorder)
    return recorder.events
