"""Config 命令 — `inkflow config <action>`."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.config import (
    CONFIG_WHITELIST,
    InkFlowConfig,
    config,
    save_config_json,
)
from inkflow.logging import instrument

app = typer.Typer(name="config", help="系统配置管理", no_args_is_help=True)


@app.command("show")
@instrument(caller_type="cli")
def show_config(ctx: typer.Context) -> None:
    """展示当前配置."""
    cli_ctx: CliContext = ctx.obj
    result = {
        "default_model": config.llm_default_model,
        "default_temperature": config.llm_temperature,
        "context_max_ratio": config.context_max_ratio,
        "context_default_window": config.context_default_window,
        "server_host": config.server_host,
        "server_port": config.server_port,
        "data_dir": str(config.data_dir),
    }
    print_result(cli_ctx, result)


@app.command("set")
@instrument(caller_type="cli")
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="配置 key"),
    value: str = typer.Argument(..., help="配置 value"),
) -> None:
    """设置配置项（写入 config.json）."""
    cli_ctx: CliContext = ctx.obj

    # #266：data-dir 特殊——写入 instance.env（固定锚点），不走 config.json
    if key == "data-dir":
        raw = value.strip()
        if not raw:
            print_error(cli_ctx, "CONFIG_ERROR", "值不合法: 数据目录不能为空", exit_code=1)
            return
        try:
            # 延迟导入：契约测试 monkeypatch 模块属性（importlib 取 sys.modules
            # 真实模块），调用时动态解析才能命中替换后的函数
            from inkflow.core.config import save_instance_env

            resolved = save_instance_env(Path(raw))
        except OSError as e:
            print_error(cli_ctx, "CONFIG_ERROR", f"值不合法: {e}", exit_code=1)
            return
        if not cli_ctx.json_output:
            typer.echo(f"✅ data-dir = {resolved}")
            typer.echo("⚠ 数据目录将在重启后生效")
        else:
            print_result(
                cli_ctx,
                {"key": "data-dir", "value": str(resolved), "restart_required": True},
            )
        return

    if key not in CONFIG_WHITELIST:
        allowed = ", ".join(CONFIG_WHITELIST)
        print_error(
            cli_ctx,
            "CONFIG_ERROR",
            f"未知配置项: {key}（允许: {allowed}）",
            exit_code=2,
        )
        return

    field_name = CONFIG_WHITELIST[key]

    # 类型转换与校验
    try:
        parsed: float | int | str
        if field_name in ("llm_temperature", "context_max_ratio"):
            parsed = float(value)
        elif field_name in ("server_port", "context_default_window"):
            parsed = int(value)
        else:
            parsed = value
        InkFlowConfig.model_validate({field_name: parsed})
    except (ValueError, ValidationError) as e:
        print_error(cli_ctx, "CONFIG_ERROR", f"值不合法: {e}")
        return

    save_config_json(config.data_dir, {field_name: parsed})
    if not cli_ctx.json_output:
        typer.echo(f"✅ {key} = {value}")
    else:
        print_result(cli_ctx, {"key": key, "value": parsed})
