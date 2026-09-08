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


# ---------------------------------------------------------------------------
# #981 — character update --role-rank / --extra-json 扩参契约（RED）
# 契约规则（父侧定稿）: .hermes/plans/red-981-b-character.md 规则 1-8。
# 未实现前: CLI 尚不识别上述两选项 → click 拒绝未知选项 exit 2，期望值断言失败即 RED。
# ---------------------------------------------------------------------------


def test_981_character_update_name_only_has_no_extra(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则1+7：仅 --name → body 只含 name 且不含 extra 键（exclude_unset 零破坏）。"""
    fake_http_client.patch.return_value = _make_character(name="新名")

    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--name", "新名"],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    call = fake_http_client.patch.await_args
    assert call.kwargs["json"] == {"name": "新名"}
    assert "extra" not in call.kwargs["json"]


def test_981_character_update_role_rank_sets_extra(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则2：--role-rank protagonist → body extra == {"role_rank": "protagonist"}。"""
    fake_http_client.patch.return_value = _make_character(extra={"role_rank": "protagonist"})

    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--role-rank", "protagonist"],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    call = fake_http_client.patch.await_args
    assert call.kwargs["json"] == {"extra": {"role_rank": "protagonist"}}


def test_981_character_update_extra_json_passes_full_object(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则3：--extra-json 合法对象 → body extra 为解析后的完整 dict。"""
    fake_http_client.patch.return_value = _make_character(
        extra={"role_rank": "major", "origin": "蜀山"}
    )

    result = cli_runner.invoke(
        app,
        [
            "update",
            "--id",
            str(uuid.uuid4()),
            "--extra-json",
            '{"role_rank": "major", "origin": "蜀山"}',
        ],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    call = fake_http_client.patch.await_args
    assert call.kwargs["json"]["extra"] == {"role_rank": "major", "origin": "蜀山"}


def test_981_character_update_both_extra_options_conflict(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则4：--role-rank + --extra-json 同传 → 本地冲突报错，不发 HTTP。"""
    result = cli_runner.invoke(
        app,
        [
            "update",
            "--id",
            str(uuid.uuid4()),
            "--role-rank",
            "protagonist",
            "--extra-json",
            '{"role_rank": "major"}',
        ],
        obj=CliContext(),
    )

    assert result.exit_code == 1
    assert "❌" in result.stderr
    fake_http_client.patch.assert_not_awaited()


def test_981_character_update_extra_json_invalid_rejected(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则5：--extra-json 非法 JSON（'{bad'）→ VALIDATION_ERROR，不发 HTTP。"""
    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--extra-json", "{bad"],
        obj=CliContext(),
    )

    assert result.exit_code == 1
    assert "❌" in result.stderr
    fake_http_client.patch.assert_not_awaited()


def test_981_character_update_extra_json_non_object_list_rejected(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则6a：--extra-json '[1, 2]' 非对象 → VALIDATION_ERROR，不发 HTTP。"""
    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--extra-json", "[1, 2]"],
        obj=CliContext(),
    )

    assert result.exit_code == 1
    assert "❌" in result.stderr
    fake_http_client.patch.assert_not_awaited()


def test_981_character_update_extra_json_non_object_string_rejected(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则6b：--extra-json '"x"' 非对象 → VALIDATION_ERROR，不发 HTTP。"""
    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--extra-json", '"x"'],
        obj=CliContext(),
    )

    assert result.exit_code == 1
    assert "❌" in result.stderr
    fake_http_client.patch.assert_not_awaited()


def test_981_character_update_role_rank_pass_through_no_enum_check(
    cli_runner: CliRunner, fake_http_client
) -> None:
    """#981 规则8：--role-rank boss（非枚举值）→ 不做本地校验，透传 body extra。"""
    fake_http_client.patch.return_value = _make_character(extra={"role_rank": "boss"})

    result = cli_runner.invoke(
        app,
        ["update", "--id", str(uuid.uuid4()), "--role-rank", "boss"],
        obj=CliContext(),
    )

    assert result.exit_code == 0
    call = fake_http_client.patch.await_args
    assert call.kwargs["json"] == {"extra": {"role_rank": "boss"}}
