"""数据面变更事件信封（#992 / ADR-053 D1，spec §15.2.1）。

契约来源
--------
- specs/f23-sse/spec.md §15.2.1（字段 / 默认值 / frozen）、§15.5.1（帧 schema）、
  §15.2.3（作用域分类：全局域 project_id=None）、§15.2.4（source 判定链）。

设计决策
--------
- **纯 dataclass（非 Pydantic）**：事件是内核内部传输载体，不进 OpenAPI /
  请求校验——镜像 F23 §2.1 `WritingStreamEvent` 的同类裁决。
- **零框架依赖**：domain 层不得 import 任何框架（ADR-002/015）；本模块只用标准库。
- **字段不可变**：frozen=True——事件一经发布即不可改写，避免订阅者互相观察
  到不同值（发布语义 = 一次性快照信号）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataChangeEvent:
    """数据面变更事件 — service 写路径末尾发布，SSE 层序列化为帧（spec §15.5）。"""

    domain: str
    """变更域（= 资源类型）：project|chapter|volume|character|character_group|
    character_relation|outline|plot_point|story_arc|world_setting|world_category|
    map|map_pin|foreshadowing|timeline_event|memory|agent_template|agent|
    knowledge_relation|session|skill|settings|provider_config|draft。"""

    op: str
    """操作类型：create|update|delete（语义化动作如 move/set_default 统一映射为 update）。"""

    resource_id: str
    """被变更资源的标识（UUID 字符串或整型主键字符串）。"""

    project_id: str | None = None
    """所属项目 UUID 字符串；**全局域为 None**（spec §15.2.3 作用域分类）。"""

    source: str = "unknown"
    """发起方：gui|cli|mcp|agent|scheduler|unknown（self-originated 过滤用，D3）。"""

    entity_id: str | None = None
    """向后兼容别名（= resource_id）；ADR-053 原信封字段名（spec §15.2.1）。"""

    traceparent: str | None = None
    """W3C traceparent（复用 #931 上下文，spec §15.9）；无上下文时为 None。"""

    occurred_at: str | None = None
    """事件产生时刻（ISO-8601 UTC，遵循 ADR-055）；调试/排序用。"""
