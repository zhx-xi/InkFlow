"""#1011 std→loguru 拦截桥 RED 契约 + 守护测试.

缺陷背景（#1011，已终裁）
-------------------------
v0.13.0-rc6 打包产物冷启动全新库：reindex 成功 → 立即 retrieve 首调 500。stack trace 证明
服务层自愈（_extraction_rag.py:489 except VectorStoreError → reindex → 第二次 retrieve L497）
确实执行了，但 store 层写后落盘窗口（≈2s 双保险合计）追不上冷启动 hnsw 段落盘（实测 ≈26s
才就绪）。

同时发现观测缺陷：_extraction_rag.py 等服务层模块（22 个）用标准 logging
（logging.getLogger(__name__)），而 core/log.py::setup_logging 只配 loguru sinks、无
std→loguru 拦截桥 → 自愈 WARNING 恒不落盘，造成「自愈从未触发」的错觉。

本文件覆盖「观测缺陷」修复的 RED 契约 + 守护既有 loguru 语义不被破坏：

GREEN 义务（core/log.py）
-------------------------
setup_logging() 新增标准 logging→loguru 拦截桥（loguru 官方 InterceptHandler 配方）：
``logging.getLogger().addHandler(...)``、``getLogger().setLevel(TRACE 或 DEBUG)``、
propagate 保持。

RED 期预期（main@ 无桥实现，先 R 后 G）
--------------------------------------
- test_std_logging_routes_to_file_sink   FAIL（无桥 → 日志文件不含 std marker）
- test_bridge_handler_idempotent         FAIL（无桥 → root.handlers 无新增桥 handler）
- test_loguru_native_still_writes_same_sink PASS（loguru 原生语义未动）

隔离说明（对齐 test_log.py 手法）
---------------------------------
- setup_logging 里 logger.remove() 有全局副作用 → autouse 每用例后恢复默认 stderr sink；
- std logging 根 logger 的 handlers 亦会被桥修改 → 保存/恢复，防跨用例污染。
"""

from __future__ import annotations

import logging
import sys

import pytest
from loguru import logger

from inkflow.core import log as log_module


@pytest.fixture(autouse=True)
def _restore_log_state():
    """每用例后恢复 loguru 默认 stderr sink + std logging 根 handler，防跨用例污染。"""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _log_files(directory) -> list:
    """directory 下现有 inkflow 日志文件列表（无则空列表，RED 期安全阅读）。"""
    return sorted(directory.glob("inkflow_*.log"))


# ── 契约 1：std logging 经拦截桥进入 loguru 文件 sink（RED）──


def test_std_logging_routes_to_file_sink(tmp_path):
    """契约 1：setup_logging 后 std logging 的 WARNING 路由进 loguru 文件 sink。

    marker 经 ``logging.getLogger("inkflow.domain.services._extraction_rag").warning(...)``
    发出（镜像 #1011 服务层自愈 WARNING）；GREEN 桥生效后应出现在 tmp_path 下的
    ``inkflow_*.log`` 文件内容里。RED 无桥 → 内容不含 marker → FAIL。
    """
    marker = "自愈哨兵 TESTMARK 1011"
    log_module.setup_logging(log_dir=tmp_path)
    logging.getLogger("inkflow.domain.services._extraction_rag").warning(marker)

    contents = "\n".join(p.read_text(encoding="utf-8") for p in _log_files(tmp_path))
    assert marker in contents, "std→loguru 桥未生效：日志文件缺少自愈哨兵标记"


# ── 契约 2：loguru 原生 writer 仍写同一文件 sink（守护，不应被桥破坏）──


def test_loguru_native_still_writes_same_sink(tmp_path):
    """守护：桥不破坏 loguru 原生 logger.warning → 仍写入同一文件 sink。

    GREEN 义务须保持 setup_logging 既有 loguru 文件 sink 语义不变；桥只是「追加」一条
    std→loguru 渠道，不得移除/淹没 loguru 原生流转。
    """
    marker = "native-loguru-1011"
    log_module.setup_logging(log_dir=tmp_path)
    logger.warning(marker)

    files = _log_files(tmp_path)
    assert files, "setup_logging 未创建 loguru 文件 sink（前置：file sink 应存在）"
    contents = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert marker in contents, "loguru 原生 warning 未写入文件 sink（桥破坏原生语义？）"


# ── 契约 3：重复 setup_logging 不叠加 std 桥 handler（幂等，RED）──


def test_bridge_handler_idempotent(tmp_path):
    """契约 3：重复 setup_logging 不叠加 std 桥 handler（root.handlers 中桥 handler 数 == 1）。

    GREEN 义务桥用 ``logging.getLogger().addHandler(...)``；若实现不守卫幂等，重复调用会叠加
    多个桥 handler → 本用例 FAIL。RED 无桥 → 新增 handler 为 0 → FAIL。
    """
    root = logging.getLogger()
    before = list(root.handlers)

    log_module.setup_logging(log_dir=tmp_path)
    log_module.setup_logging(log_dir=tmp_path)

    added = [h for h in root.handlers if h not in before]
    assert (
        len(added) == 1
    ), f"std 桥 handler 应恰好 1 个（防重复 setup_logging 叠加/漏装），实际新增 {len(added)}"
