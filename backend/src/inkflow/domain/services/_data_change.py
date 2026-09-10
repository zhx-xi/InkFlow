"""数据面变更事件发布统一辅助（#992 / ADR-053 D1，spec §15.3.3）。

契约来源
--------
- specs/f23-sse/spec.md §15.3.3（发布点形态 + 统一辅助签名）、
  §15.2.4（source 判定链「显式参数 > contextvar > "unknown"」）、
  §15.9（traceparent 复用 #931 上下文，不重复造）。

关键不变量（spec §15.3.3）
--------------------------
1. **写路径成功后才发布**——由调用方保证（域写方法末尾调用）；写失败/返回 None
   不发布（避免 GUI 拉取到不存在的资源）。
2. **发布绝不抛异常、绝不阻断写路径**——内部 try/except 兜底 + warning。
3. **不伪造字段**：project_id 取不到时发 None（GUI 侧退化为全项目刷新，§15.6.3），
   不做额外查询、不编造 id。

分层说明（AGENTS.md §4.2）
--------------------------
发布辅助位于 domain/services（spec §15.11 文件结构），而总线实现在
infrastructure/，故对总线的取用为**函数内局部 import**（镜像 agent_service 等
既有 domain→infrastructure 的惰性取用形态），模块顶层保持 domain 层零
infrastructure 依赖。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime

from inkflow.domain.models.data_change_event import DataChangeEvent
from inkflow.logging.trace import get_trace_context, make_traceparent

logger = logging.getLogger(__name__)

#: 请求级 source 标记（X-Inkflow-Source → contextvar，spec §15.2.4）。
#: API 中间件（`api/middleware/source.py`，批次 A3）写入；未标记 → "unknown"。
_source_context: ContextVar[str | None] = ContextVar("inkflow_data_change_source", default=None)

#: 未标记发起方时的兜底（spec §15.2.4 判定链末端）
UNKNOWN_SOURCE = "unknown"


def set_event_source(source: str) -> Token[str | None]:
    """设置当前上下文的事件发起方标记，返回 Token 供 reset（镜像 trace contextvar）。"""
    return _source_context.set(source)


def reset_event_source(token: Token[str | None]) -> None:
    """按 set 返回的 token 复位 source ContextVar。"""
    _source_context.reset(token)


def _iso_utc_now() -> str:
    """当前时刻的 ISO-8601 UTC 字符串（`Z` 后缀，ADR-055：存储/传输一律 UTC）。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _traceparent_or_none() -> str | None:
    """复用 #931 上下文生成 W3C traceparent；无上下文 → None（spec §15.9 边界）。"""
    ctx = get_trace_context()
    return make_traceparent(ctx) if ctx is not None else None


async def publish_change(
    domain: str,
    op: str,
    resource_id: object,
    project_id: object | None,
    *,
    source: str | None = None,
) -> None:
    """发布数据面变更事件（尽力而为，绝不抛异常，绝不阻断写路径，spec §15.3.3）。

    参数
    ----
    domain: 变更域（= 资源类型），如 `map` / `agent_template` / `character`。
    op: `create` | `update` | `delete`（语义化动作统一映射为 update）。
    resource_id: 被变更资源标识（UUID | int 主键）→ 内部 `str()`。
    project_id: 所属项目（UUID | None）；全局域传 None（§15.2.3）。
    source: 发起方；None → 解析链「contextvar > "unknown"」（§15.2.4）。
    """
    try:
        resource_id_str = str(resource_id)
        event = DataChangeEvent(
            domain=domain,
            op=op,
            resource_id=resource_id_str,
            project_id=None if project_id is None else str(project_id),
            source=source or _source_context.get() or UNKNOWN_SOURCE,
            entity_id=resource_id_str,  # 兼容别名恒等于 resource_id（§15.2.1）
            traceparent=_traceparent_or_none(),
            occurred_at=_iso_utc_now(),
        )
        from inkflow.infrastructure.events import get_event_bus  # 惰性：domain 顶层零 infra 依赖

        await get_event_bus().publish(event)
    except Exception as exc:
        # 事件是尽力而为的失效信号：发布失败绝不影响写入结果（ADR-053 影响节）
        logger.warning("变更事件发布失败（已忽略，不影响写路径）: %s", exc)
