"""结构化日志配置 — 基于 loguru。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from inkflow.core.config import config
from inkflow.logging.schema import StructuredLogRecord
from inkflow.logging.store import StructuredLogStore

if TYPE_CHECKING:
    from loguru import Message  # 仅类型注解用（运行时 loguru 0.7.3 未导出 Message）


def _norm_sink_level(name: str) -> str:
    """loguru 级别名归一："WARNING" → "WARN"（与 store/前端查询口径对齐），其余原样。"""
    return "WARN" if name == "WARNING" else name


def _structured_sink(message: Message) -> None:
    """结构化 sink：loguru record → StructuredLogRecord → 落 StructuredLogStore。

    setup_logging 追加的第三类 sink（B1 #496）：仅接收带 caller_type 的 bind
    记录（filter 把关）；store 目录 per-call 从 config.data_dir 取（测试
    monkeypatch config.data_dir 即隔离，勿启动期固化）。整体 try/except：
    日志故障静默，绝不上抛业务（contract-496 §1）。
    """
    try:
        record = message.record
        rec = StructuredLogRecord(
            level=_norm_sink_level(record["level"].name),
            logger=record["name"] or "inkflow",  # record["name"] 类型为 str | None；运行时恒非空
            timestamp=record["time"],
            **record["extra"],
        )
        StructuredLogStore(config.data_dir / "logs" / "structured").append(rec)
    except Exception:
        pass


def resolve_log_dir() -> Path:
    """解析日志目录为绝对路径 — 基于包根（backend/logs），与运行时 cwd 无关。

    bug 背景（Issue #11）：文件 sink 使用相对路径 ``logs/...`` 时，日志落点
    随进程 cwd 漂移。此处从模块文件位置向上定位 backend 根目录，保证稳定。
    F51 修正（ADR-044）：frozen 打包模式下 __file__ 指向包内路径（parents[3]
    不再落到可写 backend 根）→ 日志落 config.data_dir/logs（默认 %APPDATA%/InkFlow/logs）。
    """
    if getattr(sys, "frozen", False):
        return config.data_dir / "logs"
    # backend/src/inkflow/core/log.py → parents[3] = backend 根目录
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "logs"


def setup_logging(log_dir: Path | None = None) -> None:
    """初始化全局日志配置。

    Args:
        log_dir: 日志目录（绝对路径）。默认基于包根解析为 backend/logs，
            避免相对路径导致日志落点随进程 cwd 漂移（Issue #11）。
    """
    logger.remove()  # 移除默认 handler
    logger.add(
        sys.stderr,
        level="DEBUG" if config.debug else config.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "| <level>{level: <8}</level> "
            "| <cyan>{name}</cyan>:<cyan>{line}</cyan> "
            "- <level>{message}</level>"
        ),
        colorize=True,
    )
    target_dir = log_dir if log_dir is not None else resolve_log_dir()
    logger.add(
        target_dir / "inkflow_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )
    # 第三类 sink：结构化记录（log_structured / @instrument 埋点）落 store
    # （B1 #496）；level 与 console 同级切分（debug=False 默认关 DEBUG），
    # filter 只收带 caller_type 的 bind 记录。注册在文件 sink 之后 →
    # handlers[0] 仍为 stderr（既有测试守护，顺序不变）。
    logger.add(
        _structured_sink,
        level="DEBUG" if config.debug else config.log_level,
        filter=lambda record: "caller_type" in record["extra"],
    )
