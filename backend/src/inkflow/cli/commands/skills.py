"""skills 命令组 — 用户自定义 skills 导入与管理（spec §4，纯本地文件操作）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.cli.skills_parser import SkillValidationError, parse_skill_metadata
from inkflow.core.config import config

app = typer.Typer(name="skills", help="用户自定义 skills 导入与管理", no_args_is_help=True)


def _skills_root() -> Path:
    """默认目标根：config.data_dir / skills（动态读取，测试可 monkeypatch 实例属性）。"""
    return config.data_dir / "skills"


def _count_files(directory: Path) -> int:
    """统计目录下文件总数（含子目录）。"""
    return sum(1 for p in directory.rglob("*") if p.is_file())


@app.command("install")
def install(
    ctx: typer.Context,
    source: str = typer.Argument(..., help="含 SKILL.md 的 skill 包目录路径"),
    target: Path | None = typer.Option(
        None, "--target", help="覆盖默认目标根（默认 data_dir/skills）"
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已存在同名 skill"),
) -> None:
    """导入用户自定义 skill 包到 data_dir/skills/<name>/。"""
    cli_ctx: CliContext = ctx.obj
    root = target if target is not None else _skills_root()
    src = Path(source)

    if not src.is_dir() or not (src / "SKILL.md").is_file():
        print_error(cli_ctx, "SKILLS_SOURCE_INVALID", f"源目录无效（不存在或缺少 SKILL.md）: {src}")
        return

    try:
        text = (src / "SKILL.md").read_text(encoding="utf-8")
    except OSError as e:
        print_error(cli_ctx, "SKILLS_SOURCE_INVALID", f"读取 SKILL.md 失败: {e}")
        return

    try:
        meta = parse_skill_metadata(text, src.name)
    except SkillValidationError as e:
        print_error(cli_ctx, e.code, e.message)
        return

    dest = root / meta.name
    if dest.exists() and not force:
        print_error(
            cli_ctx,
            "ALREADY_INSTALLED",
            f"同名 skill 已存在: {meta.name}（使用 --force 覆盖）",
        )
        return

    try:
        root.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    except OSError as e:
        print_error(cli_ctx, "SKILLS_TARGET_UNWRITABLE", f"目标根不可写: {e}")
        return

    print_result(cli_ctx, {"name": meta.name, "target": str(dest), "files": _count_files(dest)})


@app.command("list")
def list_skills(ctx: typer.Context) -> None:
    """列出已导入 skills（name/description/路径/校验状态）。"""
    cli_ctx: CliContext = ctx.obj
    root = _skills_root()
    entries: list[dict] = []
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or not (child / "SKILL.md").is_file():
                continue
            try:
                meta = parse_skill_metadata(
                    (child / "SKILL.md").read_text(encoding="utf-8"),
                    child.name,
                )
                entries.append(
                    {
                        "name": meta.name,
                        "description": meta.description,
                        "path": str(child),
                        "status": "ok",
                    }
                )
            except SkillValidationError as e:
                entries.append(
                    {
                        "name": child.name,
                        "description": "",
                        "path": str(child),
                        "status": "invalid",
                        "error": {"code": e.code, "message": e.message},
                    }
                )
    print_result(cli_ctx, {"skills": entries})


@app.command("verify")
def verify_skills(
    ctx: typer.Context,
    name: str | None = typer.Option(None, "--name", help="只校验指定 skill"),
) -> None:
    """校验已导入 skills 的 frontmatter 合规性。"""
    cli_ctx: CliContext = ctx.obj
    root = _skills_root()
    if name is not None:
        targets: list[tuple[str, Path]] = [(name, root / name)]
    elif root.is_dir():
        targets = [
            (child.name, child)
            for child in sorted(root.iterdir(), key=lambda p: p.name)
            if child.is_dir() and (child / "SKILL.md").is_file()
        ]
    else:
        targets = []

    if not targets:
        print_error(cli_ctx, "NOT_FOUND", "未找到任何可校验的 skill")
        return

    last_name: str | None = None
    for dir_name, target in targets:
        skill_md = target / "SKILL.md"
        if not skill_md.is_file():
            print_error(cli_ctx, "NOT_FOUND", f"未找到 SKILL.md: {dir_name}")
            return
        try:
            meta = parse_skill_metadata(skill_md.read_text(encoding="utf-8"), dir_name)
        except SkillValidationError as e:
            print_error(cli_ctx, e.code, e.message)
            return
        last_name = meta.name

    assert last_name is not None
    print_result(
        cli_ctx,
        {
            "name": last_name,
            "checks": {"frontmatter": True, "name": True, "description": True},
            "status": "ok",
        },
    )


@app.command("remove")
def remove_skill(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="skill 名称"),
) -> None:
    """删除已导入的 skill 目录。"""
    cli_ctx: CliContext = ctx.obj
    dest = _skills_root() / name
    if not dest.is_dir():
        print_error(cli_ctx, "NOT_FOUND", f"skill 不存在: {name}")
        return
    try:
        shutil.rmtree(dest)
    except OSError as e:
        print_error(cli_ctx, "SKILLS_TARGET_UNWRITABLE", f"删除失败: {e}")
        return
    print_result(cli_ctx, {"removed": name})
