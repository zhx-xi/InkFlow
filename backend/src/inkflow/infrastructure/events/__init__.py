"""数据面变更事件基础设施 — 进程内 EventBus（#992 / ADR-053 D1，spec §15.2.2）。

总线放 infrastructure/ 而非 domain/：订阅/投递是**进程内传输实现**，
domain 只定义事件模型（`domain/models/data_change_event.py`）。
"""

from inkflow.infrastructure.events.event_bus import EventBus, get_event_bus

__all__ = [
    "EventBus",
    "get_event_bus",
]
