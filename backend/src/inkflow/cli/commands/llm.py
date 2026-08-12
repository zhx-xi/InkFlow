"""LLM 命令 — `inkflow llm <action>`."""

from __future__ import annotations

import asyncio
import json
from getpass import getpass

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import mask_key, print_error, print_result
from inkflow.core.config import config
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
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


def _run_async(coro):
    return asyncio.run(coro)


def _run(cli_ctx, coro_fn):
    """执行内核调用并映射 HTTP 异常 → print_error 信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")


provider_app = typer.Typer(name="provider", help="Provider 注册表管理", no_args_is_help=True)


@provider_app.command("list")
def provider_list(ctx: typer.Context) -> None:
    """列出 Provider 注册表"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/provider-configs")

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
        return
    items = data.get("items") or []
    if not items:
        typer.echo("📭 暂无 Provider")
        return
    for p in items:
        typer.echo(
            f"  [{p['id']}] {p['name']}  {p.get('default_model') or '-'}  "
            f"{'✅ 已配置 Key' if p.get('key_saved') else '未配置 Key'}"
        )


@provider_app.command("get")
def provider_get(
    ctx: typer.Context,
    provider_id: str = typer.Option(..., "--id", help="Provider ID"),
) -> None:
    """查看 Provider 注册表条目"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/provider-configs/{provider_id}")

    data = _run(cli_ctx, _impl)
    print_result(cli_ctx, data)


@provider_app.command("create")
def provider_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Provider 名称"),
    base_url: str | None = typer.Option(None, "--base-url"),
    default_model: str | None = typer.Option(None, "--default-model"),
    models_json: str | None = typer.Option(None, "--models-json", help="模型列表 JSON"),
    max_retries: int | None = typer.Option(None, "--max-retries"),
    timeout: int | None = typer.Option(None, "--timeout"),
) -> None:
    """创建 Provider 注册表条目"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {"name": name}
    if base_url is not None:
        body["base_url"] = base_url
    if default_model is not None:
        body["default_model"] = default_model
    if max_retries is not None:
        body["max_retries"] = max_retries
    if timeout is not None:
        body["timeout"] = timeout
    if models_json is not None:
        try:
            body["models"] = json.loads(models_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--models-json 不是合法 JSON: {models_json}")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/provider-configs", json=body)

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    else:
        typer.echo(f"✅ Provider [{data['name']}] 已创建")


@provider_app.command("update")
def provider_update(
    ctx: typer.Context,
    provider_id: str = typer.Option(..., "--id", help="Provider ID"),
    name: str | None = typer.Option(None, "--name", help="Provider 名称"),
    base_url: str | None = typer.Option(None, "--base-url"),
    default_model: str | None = typer.Option(None, "--default-model"),
    models_json: str | None = typer.Option(None, "--models-json", help="模型列表 JSON"),
    max_retries: int | None = typer.Option(None, "--max-retries"),
    timeout: int | None = typer.Option(None, "--timeout"),
) -> None:
    """更新 Provider 注册表条目"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {}
    if name is not None:
        body["name"] = name
    if base_url is not None:
        body["base_url"] = base_url
    if default_model is not None:
        body["default_model"] = default_model
    if max_retries is not None:
        body["max_retries"] = max_retries
    if timeout is not None:
        body["timeout"] = timeout
    if models_json is not None:
        try:
            body["models"] = json.loads(models_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--models-json 不是合法 JSON: {models_json}")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/provider-configs/{provider_id}", json=body)

    data = _run(cli_ctx, _impl)
    print_result(cli_ctx, data)


@provider_app.command("delete")
def provider_delete(
    ctx: typer.Context,
    provider_id: str = typer.Option(..., "--id", help="Provider ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除 Provider 注册表条目"""
    cli_ctx: CliContext = ctx.obj
    if cli_ctx.json_output and not force:
        print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
    if not force and not typer.confirm(f"确定删除 Provider #{provider_id} 吗？"):
        typer.echo("已取消")
        raise typer.Exit()

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.delete(f"/provider-configs/{provider_id}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"deleted": True})
    else:
        typer.echo(f"✅ Provider #{provider_id} 已删除")


@provider_app.command("models")
def provider_models(
    ctx: typer.Context,
    provider_id: str = typer.Option(..., "--id", help="Provider ID"),
    add: list[str] = typer.Option([], "--add", help="新增模型 JSON（可重复）"),
    remove: list[str] = typer.Option([], "--remove", help="移除模型 id（可重复）"),
    set_json: str | None = typer.Option(None, "--set-json", help="全量替换 models JSON"),
) -> None:
    """管理 Provider 模型列表"""
    cli_ctx: CliContext = ctx.obj
    if set_json is not None and (add or remove):
        raise typer.BadParameter("--set-json 与 --add/--remove 互斥")

    parsed_set: list | None = None
    parsed_add: list = []
    if set_json is not None:
        try:
            parsed_set = json.loads(set_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--set-json 不是合法 JSON: {set_json}")
    else:
        for item in add:
            try:
                parsed_add.append(json.loads(item))
            except json.JSONDecodeError:
                print_error(cli_ctx, "VALIDATION_ERROR", f"--add 不是合法 JSON: {item}")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            if parsed_set is not None:
                return await client.patch(
                    f"/provider-configs/{provider_id}", json={"models": parsed_set}
                )
            existing = await client.get(f"/provider-configs/{provider_id}")
            models = list(existing.get("models") or [])
            models.extend(parsed_add)
            if remove:
                models = [m for m in models if m["id"] not in remove]
            return await client.patch(f"/provider-configs/{provider_id}", json={"models": models})

    data = _run(cli_ctx, _impl)
    print_result(cli_ctx, data)


@app.command("test")
def test_llm(
    ctx: typer.Context,
    provider: str = typer.Option(..., "--provider"),
    api_key: str = typer.Option(..., "--api-key", help="API Key（仅本次请求，不落盘）"),
    model: str | None = typer.Option(None, "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
) -> None:
    """测试 Provider 连通性（API Key 仅本次请求，不落盘）"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {"provider": provider, "api_key": api_key}
    if model is not None:
        body["model"] = model
    if base_url is not None:
        body["base_url"] = base_url

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/settings/llm/test", json=body)

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif data.get("ok"):
        typer.echo(f"✅ {data['message']}")
    else:
        typer.echo(f"❌ {data['message']}", err=True)


key_app = typer.Typer(name="key", help="API Key 本地文件管理", no_args_is_help=True)


@key_app.command("remove")
def key_remove(
    ctx: typer.Context,
    provider: str = typer.Option(..., "--provider"),
) -> None:
    """删除本地保存的 Provider API Key"""
    cli_ctx: CliContext = ctx.obj
    km = _get_key_manager()
    try:
        km.delete(provider)
    except FileNotFoundError:
        print_error(cli_ctx, "NOT_FOUND", f"Provider {provider} 未配置 API Key")
    if not cli_ctx.json_output:
        typer.echo(f"✅ Provider {provider} 的 API Key 已删除")
    else:
        print_result(cli_ctx, {"provider": provider, "status": "removed"})


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


app.add_typer(provider_app)
app.add_typer(key_app)
