"""F20/#942 CLI 进程日志桥接 — 叶子命令审计 checkpoint → POST /logs。

CLI 子命令（inkflow project/chapter/write/...）的 @instrument(caller_type="cli")
埋点运行在 inkflow CLI 进程内；该进程不做内核 setup_logging()，loguru 默认
sink=stderr，不进内核 StructuredLogStore → GUI 日志页「内核」分类 CLI 操作
痕迹永远缺失（审计盲区，issue #942）。本模块在根 app 的 Command.main 入口
（cli_log_sink）内：包装命令模块 ensure_kernel（成功→attach）与
typer.core.TyperCommand.invoke（每次叶子命令恰一条审计 checkpoint），经通用
引擎 inkflow.logging.bridge 转发到内核 /api/v1/logs。
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Iterator
from typing import Any

import httpx
import typer
from typer.core import TyperCommand

from inkflow.logging.bridge import LogForwarder, log_sink
from inkflow.logging.schema import log_structured


def _make_client(port: int, token: str) -> httpx.Client:
    """构造转发 client（模块级工厂缝，测试 monkeypatch 点）；契约同通用引擎。"""
    from inkflow.logging.bridge import _make_client as _engine_make_client

    return _engine_make_client(port, token)


def _default_client(port: int, token: str) -> Any:
    """运行时读本模块 _make_client（patch 生效）；返回引擎 httpx client。"""
    return _make_client(port, token)


_cli_forwarder: LogForwarder | None = None


def get_cli_forwarder() -> LogForwarder:
    """返回 CLI 进程级转发单例（与 mcp 单例分离，互不污染）。"""
    global _cli_forwarder
    if _cli_forwarder is None:
        _cli_forwarder = LogForwarder(client_factory=_default_client)
    return _cli_forwarder


def _promote_project_id(value: object) -> int | None:
    """纯数字串 → int；UUID/缺失 → None（顶层过滤面，params 保留原串）。"""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _ctx_below_root(ctx: Any) -> list[str]:
    """收集叶子上下文 info_name 链：自叶子向根（parent None）回溯后取根之下的正序名字。"""
    chain: list[str] = []
    node: Any = ctx
    while node is not None:
        name = getattr(node, "info_name", None)
        if isinstance(name, str) and name:
            chain.append(name)
        parent = getattr(node, "parent", None)
        if parent is None:
            break
        node = parent
    chain.reverse()
    # chain[0] 为根上下文（info_name="inkflow"），事件/group 均不含根
    return chain[1:] if len(chain) > 1 else []


def _exit_error_code(exc: typer.Exit) -> str | None:
    """print_error 抛出的 Exit 是否代表 CLI 内部崩溃（X_CLI_ERROR）。

    typer.Exit 在 _run 的 except 处理器内经 print_error 抛出时，Python 把被
    处理的原始异常隐式链接为 __context__；HttpApiError / KernelStartupError
    属预期业务面不加码，其余（ValueError 等）视为未预期崩溃 → X_CLI_ERROR
    （契约 4：typer.Exit 失败路径靠 print_error 语义）。
    """
    cause = exc.__context__
    if cause is None:
        return None
    from inkflow.infrastructure.http import HttpApiError
    from inkflow.infrastructure.kernel import KernelStartupError

    if isinstance(cause, (HttpApiError, KernelStartupError)):
        return None
    return "X_CLI_ERROR"


def _emit_checkpoint(ctx: Any, *, outcome: BaseException | None, duration_ms: float) -> None:
    """emit 叶子命令审计 checkpoint：白名单 params，绝不落原始选项值（正文等）。

    经 log_structured → 桥接 sink → POST /logs；日志/转发故障静默（suppress）。
    """
    below = _ctx_below_root(ctx)
    command = below[-1] if below else str(getattr(ctx, "info_name", "") or "")
    group = "-".join(below[:-1])
    raw_project_id = getattr(ctx, "params", {}).get("project_id")
    level: str
    error_code: str | None
    if outcome is None or (isinstance(outcome, typer.Exit) and outcome.exit_code == 0):
        level, error_code = "INFO", None
    elif isinstance(outcome, typer.Exit):
        level, error_code = "WARN", _exit_error_code(outcome)
    else:
        level, error_code = "WARN", "X_CLI_ERROR"
    with contextlib.suppress(Exception):
        log_structured(
            level=level,
            caller_type="cli",
            caller_name="inkflow-cli",
            event=".".join(below),
            message_key="log.event.cli_command",
            params={
                "group": group,
                "command": command,
                "project_id": str(raw_project_id) if raw_project_id is not None else None,
            },
            project_id=_promote_project_id(raw_project_id),
            error_code=error_code,
            duration_ms=duration_ms,
        )


def _make_ensure_wrapper(original: Any, forwarder: LogForwarder) -> Any:
    """构造命令模块 ensure_kernel 包装：await 原函数成功 → attach → 原样返回。"""

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        handle = await original(*args, **kwargs)
        forwarder.attach(handle.port, handle.token)
        return handle

    return wrapped


def _wrap_command_ensures(forwarder: LogForwarder) -> list[tuple[Any, Any]]:
    """包装已加载命令模块（inkflow.cli.commands* 且带 ensure_kernel）的模块属性。

    CLI 命令顶层 `from inkflow.infrastructure.kernel import ensure_kernel` 是模块
    全局查找——包装模块属性即生效；绝不新增任何 ensure_kernel 调用（零额外探测/
    零冷启动副作用）。返回 [(模块, 原值)] 供退出还原。
    """
    patched: list[tuple[Any, Any]] = []
    for name, loaded in list(sys.modules.items()):
        if not name.startswith("inkflow.cli.commands"):
            continue
        mod: Any = loaded
        original = getattr(mod, "ensure_kernel", None)
        if original is None:
            continue
        mod.ensure_kernel = _make_ensure_wrapper(original, forwarder)
        patched.append((mod, original))
    return patched


def _install_invoke_wrapper(forwarder: LogForwarder) -> tuple[bool, Any]:
    """类属性 patch typer.core.TyperCommand.invoke；返回 (是否自有, 原函数)。

    invoke 继承自已弃用的 typer._click Command——只 patch 类属性即可覆盖所有
    叶子命令实例；还原时按是否继承态删除/回填（#942 契约 3b）。
    """
    original = TyperCommand.invoke
    had_own = "invoke" in TyperCommand.__dict__

    def _invoke_with_checkpoint(self: Any, ctx: Any) -> Any:
        """调用原 invoke；每个叶子命令返回/抛出前 emit checkpoint + 尽力 flush。"""
        started = time.perf_counter()
        outcome: BaseException | None = None
        try:
            result = original(self, ctx)
        except BaseException as exc:
            outcome = exc
            raise
        finally:
            try:
                _emit_checkpoint(
                    ctx,
                    outcome=outcome,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
            finally:
                with contextlib.suppress(Exception):
                    forwarder.flush()
        return result

    TyperCommand.invoke = _invoke_with_checkpoint  # type: ignore[method-assign]  # 类属性动态 patch（契约 3b）
    return had_own, original


def _restore_invoke(state: tuple[bool, Any]) -> None:
    """还原 TyperCommand.invoke：继承态删除自有属性，自有态回填原函数。"""
    had_own, original = state
    if had_own:
        TyperCommand.invoke = original  # type: ignore[method-assign]  # 回填进入前的自有属性
    else:
        with contextlib.suppress(Exception):
            delattr(TyperCommand, "invoke")


_sink_depth = 0


@contextlib.contextmanager
def cli_log_sink() -> Iterator[None]:
    """根 CLI 入口会话：包装命令模块 ensure_kernel + TyperCommand.invoke。

    进入时（inkflow.cli.commands.* 已全部导入）包装每个已加载且带 ensure_kernel
    的命令模块属性；同时 patch TyperCommand.invoke 使每次叶子命令恰发一条审计
    checkpoint（含 finally 尽力 flush，保证记录先于 CLI 进程退出送达内核）。
    引擎复用 log_sink(get_cli_forwarder())；退出时最终 flush + 全部还原。
    """
    global _sink_depth
    forwarder = get_cli_forwarder()
    outermost = _sink_depth == 0
    _sink_depth += 1
    restored_ensures: list[tuple[Any, Any]] = []
    invoke_state: tuple[bool, Any] | None = None
    try:
        if outermost:
            restored_ensures = _wrap_command_ensures(forwarder)
            invoke_state = _install_invoke_wrapper(forwarder)
        with log_sink(forwarder):
            yield
    finally:
        _sink_depth -= 1
        if outermost:
            for mod, original in restored_ensures:
                with contextlib.suppress(Exception):
                    mod.ensure_kernel = original
            if invoke_state is not None:
                _restore_invoke(invoke_state)
