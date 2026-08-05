"""LLM 命令 — `inkflow llm <action>`."""

from __future__ import annotations

from getpass import getpass

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import mask_key, print_error, print_result
from inkflow.core.config import config
from inkflow.infrastructure.llm.key_manager import APIKeyManager

app = typer.Typer(name="llm", help="LLM Provider 配置", no_args_is_help=True)

_PROVIDER_MODELS = {
    "openai": "gpt-4o",
    "deepseek": "deepseek-chat",
    "zhipu": "glm-4.5",
    "anthropic": "claude-3-haiku-20240307",
}


def _get_key_manager() -> APIKeyManager:
    return APIKeyManager(
        secret_key=config.secret_key,
        storage_dir=config.data_dir / "keys",
    )


@app.command("list")
def list_providers(ctx: typer.Context) -> None:
    """列出已配置的 LLM Provider."""
    cli_ctx: CliContext = ctx.obj
    km = _get_key_manager()
    providers = km.list_providers()
    result = []
    for p in providers:
        default_model = _PROVIDER_MODELS.get(p, "unknown")
        try:
            key = km.load(p)
            key_status = "configured"
            key_masked = mask_key(key)
        except Exception:
            key_status = "error"
            key_masked = "****"
        result.append(
            {
                "provider": p,
                "default_model": default_model,
                "key_status": key_status,
                "key_masked": key_masked,
            }
        )
    print_result(cli_ctx, result)


@app.command("set-key")
def set_key(
    ctx: typer.Context,
    provider: str = typer.Option(..., "--provider", help="Provider 名称"),
    key: str | None = typer.Option(None, "--key", help="API Key（明文，有 shell 泄露风险）"),
) -> None:
    """设置 Provider API Key."""
    cli_ctx: CliContext = ctx.obj
    if key is not None:
        typer.echo(
            "⚠️ WARNING: 通过 --key 传递明文 Key 可能被 shell history 记录",
            err=True,
        )
    else:
        key = getpass(f"输入 {provider} API Key（不回显）: ")

    if not key or not key.strip():
        print_error(cli_ctx, "VALIDATION_ERROR", "API Key 不能为空")
        return

    km = _get_key_manager()
    try:
        km.store(provider, key.strip())
    except Exception as e:
        print_error(cli_ctx, "CONFIG_ERROR", f"Key 存储失败: {e}")
        return

    if not cli_ctx.json_output:
        typer.echo(f"✅ {provider} API Key 已保存 (mask: {mask_key(key)})")
    else:
        print_result(cli_ctx, {"provider": provider, "status": "saved"})
