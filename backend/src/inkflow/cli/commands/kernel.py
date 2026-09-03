"""内核调试命令 — `inkflow kernel status`（dev 标注，spec §4）。

非用户面命令：主要供集成测试与排障。绝不拉起内核（纯查询）。
"""

from __future__ import annotations

from pathlib import Path

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_result
from inkflow.infrastructure.kernel import state
from inkflow.logging import instrument

app = typer.Typer(
    name="kernel",
    help="内核状态调试命令（dev）",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """kernel 命令组回调（防 typer 0.27 单命令压平；不覆盖 ctx.obj）。"""


@app.command()
@instrument(caller_type="cli")
def status(ctx: typer.Context) -> None:
    """输出内核运行状态（运行中 PID/端口/版本 或 未运行）。"""
    cli_ctx: CliContext = ctx.obj
    # 状态文件路径：调用时从 config 单例读取（spec §6.1）
    from inkflow.core.config import config

    state_file: Path = config.data_dir / "kernel.json"
    st = state.read_kernel_state(state_file)
    if st is not None and state.is_process_alive(st.pid):
        # 运行中：--json 信封 {"running": true, pid, port, version}
        print_result(
            cli_ctx,
            {
                "running": True,
                "pid": st.pid,
                "port": st.port,
                "version": st.version,
            },
        )
        return
    # 未运行（无状态文件/损坏/pid 死）：{"running": false}，退出码 0
    # （状态查询不因未运行而失败，spec §4）；人类模式输出「未运行」提示
    if cli_ctx.json_output:
        print_result(cli_ctx, {"running": False})
    else:
        typer.echo("未运行")
