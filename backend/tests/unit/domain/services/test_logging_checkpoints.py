"""F57 显式 checkpoint — WARN 自愈/降级契约测试（任务 #888-S2 / spec §4.1 语义层）。

契约来源
--------
specs/f57-logging-i18n/spec.md §4 埋点矩阵（agent 编排 WARN：重试/降级/护栏触达）+
§4.1 语义层（WARN 校验失败/重试自愈/降级/护栏触达 → error_code + 上下文 + 标已自愈）
+ §2.2（日志结构：message_key / error_code / params）。

目标：**真实领域函数** agent_service._apply_agent_order 的护栏/降级路径（纯函数、无 DB，
确定性可测）。设计目标：非法 agent_order 触达护栏 → 回退默认拓扑（already-healed），
此时必须发 **结构化 WARN**（经 log_structured，loguru 通道）：含 error_code +
message_key(log.check.*) + 上下文 params + 已自愈标记 params["self_healed"]=True。

注：S1 基座 agent_service.py 用 stdlib ``logging.getLogger(__name__)``（第 36 行）打裸
logger.warning —— 走 stdlib 通道，**不会**落到 loguru sink，也**无** message_key/error_code/
self_healed 字段。GREEN 必须把护栏 WARN 改为 loguru ``log_structured``。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 必须满足的契约）
════════════════════════════════════════════════════════════════════
1. _apply_agent_order(stages, agent_order, enabled_roles, template_roles=None,
   agent_source=None)（inkflow.domain.services.agent_service，纯函数）：
   - len(agent_order) > 10 → WARN + return stages（默认拓扑回退 = 自愈）
   - 展开集有跨层重复角色 → WARN + return stages
   - 缺启用角色 → WARN + return stages
2. 每个护栏 WARN 经 **log_structured**（loguru）：
   - message_key 前缀 log.check.（语义键族，与装饰器 log.call.* 区分）
   - error_code 非空且 != "X_UNCAUGHT"（后者是 @instrument 未捕获异常专用）
   - params 含已自愈标记 self_healed=True + 上下文（depth / role / missing 等）
   - 级别 WARN / loguru 警告（**loguru 内建无 ``WARN`` 级别名，其名为 ``WARNING``**：
     log_structured 收到 level="WARN" 须映射到 loguru warning，但记录 level 字符串仍为
     ``WARN``。这是 S2 对 S1 log_structured 的增量修正）

RED 阶段预期：S1 基座用 stdlib logger.warning（无 message_key/error_code/params 标记，
且不落 loguru sink）→ loguru sink 捕获为空 → 断言失败。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import sys

import pytest
from loguru import logger

from inkflow.domain.services.agent_service import _apply_agent_order


@pytest.fixture(autouse=True)
def _restore_loguru():
    """每个测试后移除全部 loguru handler 并恢复默认，避免污染其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_records(level: str = "WARNING"):
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _warn_records(records: list) -> list[dict]:
    """返回全部 loguru WARNING 级记录（loguru 内建级别名叫 WARNING，非 WARN）。"""
    return [r for r in records if r["level"].name == "WARNING"]


def _assert_selfheal_warn(rec: dict) -> None:
    """断言该 WARN 记录满足语义层自愈契约。"""
    extra = rec["extra"]
    assert extra.get("message_key", "").startswith("log.check."), (
        f"message_key 未用 log.check.*：{extra}"
    )
    assert extra.get("error_code"), f"WARN 未带 error_code：{extra}"
    assert extra["error_code"] != "X_UNCAUGHT", "自愈 WARN 不应标 X_UNCAUGHT（那是未捕获异常）"
    assert extra.get("params", {}).get("self_healed") is True, f"WARN 未标已自愈：{extra}"


class TestApplyAgentOrderWarnSelfHeal:
    """护栏/降级触达 → 结构化 WARN + 标已自愈。"""

    def test_too_deep_layers_warns_selfheal(self):
        records, sid = _capture_records("WARNING")
        try:
            result = _apply_agent_order([], [["x"] for _ in range(11)], set())
        finally:
            logger.remove(sid)
        assert result == [], "护栏应回退默认拓扑（原样返回 stages=[]）"
        warns = _warn_records(records)
        assert warns, "应触发 WARN（loguru）"
        _assert_selfheal_warn(warns[0])

    def test_duplicate_role_warns_selfheal(self):
        records, sid = _capture_records("WARNING")
        try:
            result = _apply_agent_order([], [["a", "a"]], {"a"})
        finally:
            logger.remove(sid)
        assert result == []
        warns = _warn_records(records)
        assert warns, "应触发 WARN（loguru）"
        _assert_selfheal_warn(warns[0])

    def test_missing_enabled_role_warns_selfheal(self):
        records, sid = _capture_records("WARNING")
        try:
            result = _apply_agent_order([], [["writer"]], {"architect", "writer"})
        finally:
            logger.remove(sid)
        assert result == []
        warns = _warn_records(records)
        assert warns, "应触发 WARN（loguru）"
        _assert_selfheal_warn(warns[0])
