"""#708 coverage 补测 鈥?character CLI 命令缺口分支（CliRunner + mock HTTP 客户端）。

被测模块: ``inkflow.cli.commands.character``
补齐缺口:
- ``_parse_uuid`` print_error 之后的死代码 raise（56 行）
- get 命令 character 无 group_names/group_ids 鈫?空分组显示（203->205）
- group update 传入 name/description 鈫?update_fields 两分支（551->553 / 553->554 + 554 行）
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.commands.character import _parse_uuid, app, group_app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（镜像 tests/cli 既有模式）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。"""
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.character.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.character.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_character(**overrides: object) -> dict:
    """构造 Character JSON dict（不含 group_names/group_ids 键）。"""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="林尘",
        personality="坚韧",
        background="出身贫寒",
        goals="成为强者",
        extra={},
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_group(**overrides: object) -> dict:
    """构造 CharacterGroup JSON dict。"""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="主角团",
        description="核心小队",
        sort_order=0,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def test_parse_uuid_invalid_raises_exit_after_print_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """print_error 为 no-op 时非法 UUID 走到死代码 raise typer.Exit(1)（56 行）。"""
    from inkflow.cli.commands import character as char_mod

    monkeypatch.setattr(char_mod, "print_error", lambda ctx, code, msg: None, raising=False)
    cli_ctx = CliContext()

    with pytest.raises(typer.Exit) as exc:
        _parse_uuid(cli_ctx, "not-a-uuid", "角色不存在")

    assert exc.value.exit_code == 1


def test_get_character_without_groups_renders_empty_display(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """character 无 group_names/group_ids 键 鈫?group_display 回退空数组（203->205）。"""
    fake_http_client.get.return_value = _make_character()

    result = cli_runner.invoke(
        app,
        ["get", "--id", str(uuid.uuid4())],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    assert "分组:       " in result.stdout
    fake_http_client.get.assert_awaited_once()


def test_get_character_with_group_names_skips_fallback(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """character 含 group_names → 不落入 group_ids 回退（203->205 False 分支）。"""
    fake_http_client.get.return_value = _make_character(group_names=["主角团"])

    result = cli_runner.invoke(
        app,
        ["get", "--id", str(uuid.uuid4())],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    assert "分组:       主角团" in result.stdout


def test_update_group_with_name_and_description(cli_runner: CliRunner, fake_http_client) -> None:
    """group update 传 name + description 鈫?update_fields 两分支（551->553 / 553->554）。"""
    fake_http_client.patch.return_value = _make_group(name="新队名", description="新说明")

    result = cli_runner.invoke(
        group_app,
        ["update", "--id", str(uuid.uuid4()), "--name", "新队名", "--description", "新说明"],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    assert "新队名" in result.stdout
    call_kwargs = fake_http_client.patch.await_args.kwargs
    assert call_kwargs["json"] == {"name": "新队名", "description": "新说明"}


def test_update_group_description_only_skips_name(cli_runner: CliRunner, fake_http_client) -> None:
    """group update 仅传 description → name is None 分支（551->553）。"""
    fake_http_client.patch.return_value = _make_group(name="主角团", description="新说明")

    result = cli_runner.invoke(
        group_app,
        ["update", "--id", str(uuid.uuid4()), "--description", "新说明"],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    call_kwargs = fake_http_client.patch.await_args.kwargs
    assert call_kwargs["json"] == {"description": "新说明"}
