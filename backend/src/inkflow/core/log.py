"""结构化日志配置 — 基于 loguru。"""

from __future__ import annotations

import inspect
import logging
import sys
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from inkflow.core.config import config
from inkflow.logging.schema import StructuredLogRecord
from inkflow.logging.store import StructuredLogStore

if TYPE_CHECKING:
    from loguru import Message  # 仅类型注解用（运行时 loguru 0.7.3 未导出 Message）


class InterceptHandler(logging.Handler):
    """标准 logging → loguru 拦截桥（#1011，loguru 官方 InterceptHandler 配方）。

    emit 将 stdlib LogRecord 转发到 loguru 全局 logger；root logger 装桥后，
    ``logging.getLogger(__name__)`` 打出的服务层日志（WARNING 等）也能进入
    loguru 的 stderr/文件 sink，不再「恒不落 inkflow_*.log」。

    注意：桥接记录不带 caller_type → 天然不进 _structured_sink（filter 把关），
    这是预期语义；勿改 filter（stderr/文件 sink 语义保持原样）。
    """

    def emit(self, record: logging.LogRecord) -> None:
        """把一条 stdlib LogRecord 以对应级别转发到 loguru。"""
        # #1011: 级别名映射——logging 标准级别与 loguru 内建级别同名
        # （WARNING/ERROR/...）；未知级别回退 levelno（loguru 接受数字级别）。
        level: str | int
        level_name = logging.getLevelName(record.levelno)
        try:
            level = logger.level(level_name).name
        except ValueError:
            level = record.levelno
        # 从 emit 的调用方（Handler.handle）向上回溯，每跨过一层 logging 内部帧
        # depth 加 1，直到离开 logging 模块——loguru 即可定位到业务代码的原始
        # 调用者（{name}:{line} 指向服务层而非 logging 内部帧）。
        frame = inspect.currentframe()
        frame = frame.f_back if frame is not None else None
        depth = 1
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# #1011 评审 M1：root logger 提到 INFO（inkflow.* 服务层 INFO 要落文件 sink）后，
# httpx/httpcore/chromadb/sqlalchemy 的 INFO 若经拦截桥放行，会淹没文件 sink、稀释
# 本 Issue 要浮现的服务层 WARNING。故对已知噪声三方 logger 设 WARNING 级别上限；
# config.debug=True 时跳过（调试态放行三方 INFO 是预期）。
_THIRD_PARTY_WARN_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "chromadb",
    "sqlalchemy.engine",
)


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
            timestamp=record["time"].astimezone(UTC),
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
    # #1011: std→loguru 拦截桥（观测缺陷修复）——服务层 22 个模块用标准 logging
    # 打日志，若只配 loguru sinks，WARNING 恒不落 inkflow_*.log。装到 root logger：
    # loguru sink 只走 sys.stderr/文件，不回 std logging，无循环风险，勿额外加
    # std handler。幂等守卫：先移除本模块旧桥再 add，重复 setup_logging 不叠加。
    std_root = logging.getLogger()
    for handler in list(std_root.handlers):
        if isinstance(handler, InterceptHandler):
            std_root.removeHandler(handler)
    std_root.addHandler(InterceptHandler())
    # 与 stderr sink 同口径：debug 强制 DEBUG，否则按 config.log_level，控制三方
    # std 噪声（否则第三方 std DEBUG 会经桥灌满文件 sink）。
    std_root.setLevel(logging.DEBUG if config.debug else config.log_level)
    # #1011 评审 M1：三方 INFO 封顶只在非调试态生效；setLevel 天然幂等，重复
    # setup_logging 每次重新 set WARNING 即保持结果一致，不会把已封级别升回去。
    if not config.debug:
        for name in _THIRD_PARTY_WARN_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
