"""#1520 负例守卫：issue 明列「无正文参数（不需要）」的命令，参数面不得被误加.

依据 `specs/f7-cli/spec.md` §4.0 范围边界（#1520）——以下命令**刻意不接**
`--content-file`（语义不符 / 无对应正文字段）：

- `project create` / `project update`（name/tags/language/target_words/config）
- `volume create` / `volume update`（title/order）
- `map pin update`（label/location 坐标类）
- `write next`（`--outline` 是提纲输入，语义不同）

本文件用**自省 + `--help` 双判据**断言参数面不变：若本轨（或后续）给这些命令
误加 `--content-file`，两条断言都会 FAIL。
"""

from __future__ import annotations

import inspect

import typer
from typer.testing import CliRunner

from inkflow.cli.commands.chapter import volume_app
from inkflow.cli.commands.map import pin_app
from inkflow.cli.commands.project import app as project_app
from inkflow.cli.commands.write import app as write_app

# (命令组 app, 子命令名) —— 均须无 --content-file
NO_CONTENT_FILE_COMMANDS: list[tuple[str, typer.Typer, str]] = [
    ("project", project_app, "create"),
    ("project", project_app, "update"),
    ("volume", volume_app, "create"),
    ("volume", volume_app, "update"),
    ("map pin", pin_app, "update"),
    ("write", write_app, "next"),
]

IDS = [f"{group}-{name}" for group, _, name in NO_CONTENT_FILE_COMMANDS]


def _has_content_file_option(app: typer.Typer, name: str) -> bool:
    """自省：该子命令的 callback 是否声明了 `--content-file` 选项."""
    for cmd in app.registered_commands:
        cmd_name = cmd.name or (cmd.callback.__name__ if cmd.callback else None)
        if cmd_name != name or cmd.callback is None:
            continue
        for param in inspect.signature(cmd.callback).parameters.values():
            default = param.default
            decls = getattr(default, "param_decls", None) or ()
            if "--content-file" in decls:
                return True
    return False


def test_no_content_file_option_registered():
    """自省判据：这些命令的 callback 不得声明 `--content-file`."""
    offenders = [
        f"{group} {name}"
        for group, app, name in NO_CONTENT_FILE_COMMANDS
        if _has_content_file_option(app, name)
    ]
    assert offenders == [], f"以下命令被误加 --content-file：{offenders}"


def test_help_does_not_list_content_file():
    """`--help` 判据：这些命令的帮助文本不得出现 `--content-file`."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    offenders = []
    for group, app, name in NO_CONTENT_FILE_COMMANDS:
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0, f"{group} {name}: {result.output}"
        if "--content-file" in result.output:
            offenders.append(f"{group} {name}")
    assert offenders == [], f"以下命令 --help 出现 --content-file：{offenders}"
