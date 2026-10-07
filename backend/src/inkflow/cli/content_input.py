"""正文双通道解析 — create/update 命令 `--content-file` 的公共实现（#1483）.

统一语义（specs/f7-cli/spec.md §4.0）：
- 内联正文参数 与 `--content-file` **互斥**（同传 → 退出码 2，stderr 文案，**不发生写入**）
- 文件**显式 UTF-8** 读取（与宿主 locale / PowerShell 代码页无关）
- 文件缺失/不可读 → `VALIDATION_ERROR` + 退出码 1（不泄漏栈回溯）
- 文件内容**原样**透传（不 strip、不做编码转换）

各命令复用本模块，禁止逐命令重复实现。
"""

from __future__ import annotations

from pathlib import Path

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error


def resolve_content(
    inline: str | None,
    content_file: str | None,
    *,
    cli_ctx: CliContext,
    inline_flag: str,
) -> str | None:
    """解析命令正文：内联 <inline_flag> / `--content-file` 双通道（互斥）.

    Args:
        inline: 内联正文参数值（create 类命令默认 `""`、update 类默认 `None`）。
        content_file: `--content-file` 文件路径。
        cli_ctx: CLI 上下文（决定错误输出形态：人类 stderr / `--json` 信封）。
        inline_flag: 内联参数名（用于互斥文案，如 `--content` / `--description` / `--background`）。

    Returns:
        解析后的正文值；两者皆缺席时原样返回 ``inline``（可能是 `None`）。
    """
    if content_file is not None and inline:
        typer.echo(f"❌ {inline_flag} 与 --content-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if content_file is None:
        return inline
    try:
        return Path(content_file).read_text(encoding="utf-8")
    except OSError:
        print_error(cli_ctx, "VALIDATION_ERROR", f"正文文件不存在或不可读: {content_file}")
        raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）
