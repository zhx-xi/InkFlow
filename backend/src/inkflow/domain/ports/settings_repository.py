"""Settings 仓储端口 — app_settings 表持久化契约。

只暴露「全量读 + 批量写」两个操作：设置域没有按单键查询/删除的需求
（消费方永远读全量、写部分），YAGNI 不建 get(key)/delete(key)。
"""

from __future__ import annotations

from typing import Protocol


class SettingsRepositoryProtocol(Protocol):
    async def get_all(self) -> dict[str, str]:
        """返回全部已持久化键值对 {key: JSON 编码 value}；空表返回 {}。"""
        ...

    async def set_many(self, values: dict[str, str]) -> None:
        """批量 upsert（INSERT OR REPLACE）；values 为 {key: JSON 编码 value}。"""
        ...
