"""#1483 `create` / `update` 系列 `--content-file` 正文双通道 — RED 契约测试.

**spec 为唯一真相**（本文件断言全部由 spec 推导，不读实现）:

- `specs/f7-cli/spec.md` §4.0（正文双通道通用约定）+ §14.1（`--content-file` 状态流行）
- `specs/f2-chapter/spec.md` §4（v1.2）
- `specs/f9-character/spec.md` §4.1（v1.5）
- `specs/f10-world-settings/spec.md` §4.1（v1.7）
- `specs/f11-outline/spec.md` §4.1（v1.2）

**范围** = 四个模块的**实体级** create/update（8 命令）:
`world create|update` · `chapter create|update` · `outline create|update` ·
`character create|update`。

**断言族（每个命令同构）**:

- N1 文件原样落库: `--content-file <utf8 中文文件>` → 目标字段逐字符等于文件内容
  （无乱码）。RED 预期 FAIL（参数不存在）。
- N2 互斥: 内联正文参数 与 `--content-file` 同传 → 退出码 2 + 「不能同时使用」文案,
  且**不发生写入**（HTTP 未被调用）。RED 预期 FAIL（RED 下为 `No such option`）。
- N3 文件缺失: `--content-file` 指向不存在文件 → 退出码 1 + `VALIDATION_ERROR`
  错误信封 + 可读消息（非栈回溯）。RED 预期 FAIL。
- N4 长正文: 文件含换行 > 32KB 文本 → 成功且逐字符落库。RED 预期 FAIL。
- N5 负例守卫: 仅内联正文 → 目标字段 == 内联值 + 信封结构不变。当前 PASS（守住）。
- N6 `--json` 成功信封 `{"ok": true, "data": ...}` 不变。当前 PASS（守住）。

CLI 测试约定（AGENTS.md §7.2）：经 `ensure_kernel` + `InkFlowHTTPClient` 的**模块级
patch**替代 DB；不使用 `monkeypatch.setenv("INKFLOW_DATABASE_URL", ...)`。
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.chapter import chapter_app
from inkflow.cli.commands.character import app as character_app
from inkflow.cli.commands.outline import app as outline_app
from inkflow.cli.commands.world import app as world_app
from inkflow.cli.context import CliContext

PID = "3f2e1d4a-0000-4000-8000-000000000001"
SID = "3f2e1d4a-0000-4000-8000-000000000002"
CID = "3f2e1d4a-0000-4000-8000-000000000003"
OID = "3f2e1d4a-0000-4000-8000-000000000004"
CHID = "3f2e1d4a-0000-4000-8000-000000000005"

# 含中文 + 换行 + 首尾空白的正文：验证「原样落库」（不 strip、不转码）
FILE_BODY = "\n九幽宗·总纲\n\n天地灵气复苏，宗门林立。\n  第二行带前导空格。\n"
INLINE_BODY = "内联正文（负例守卫）"
# > 32KB（Windows 命令行内联长度上限）的长正文，含换行
LONG_BODY = "长正文段落，用于验证命令行长度限制与 UTF-8 读文件通道。\n" * 1500


class Case:
    """一个「命令 × 正文字段」样本（供参数化）。"""

    def __init__(
        self,
        case_id: str,
        module: str,
        app: Any,
        base: list[str],
        method: str,
        field: str,
        inline_flag: str,
        stub: dict[str, Any],
    ) -> None:
        self.id = case_id
        self.module = module
        self.app = app
        self.base = base
        self.method = method
        self.field = field
        self.inline_flag = inline_flag
        self.stub = stub


CASES = [
    Case(
        "world-create",
        "world",
        world_app,
        ["create", "--project-id", PID, "--name", "九幽宗"],
        "post",
        "content",
        "--content",
        {"id": str(uuid.uuid4()), "name": "九幽宗", "category": "", "content": ""},
    ),
    Case(
        "world-update",
        "world",
        world_app,
        ["update", "--id", SID],
        "patch",
        "content",
        "--content",
        {"id": SID, "name": "九幽宗", "category": "", "content": ""},
    ),
    Case(
        "chapter-create",
        "chapter",
        chapter_app,
        ["create", "--project-id", PID, "--title", "第一章"],
        "post",
        "content",
        "--content",
        {"id": str(uuid.uuid4()), "title": "第一章", "word_count": 3},
    ),
    Case(
        "chapter-update",
        "chapter",
        chapter_app,
        ["update", "--id", CID],
        "patch",
        "content",
        "--content",
        {"id": CID, "title": "第一章", "word_count": 3},
    ),
    Case(
        "outline-create",
        "outline",
        outline_app,
        ["create", "--project-id", PID, "--name", "三部曲总纲"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "name": "三部曲总纲", "description": ""},
    ),
    Case(
        "outline-update",
        "outline",
        outline_app,
        ["update", "--id", OID],
        "patch",
        "description",
        "--description",
        {"id": OID, "name": "三部曲总纲", "description": ""},
    ),
    Case(
        "character-create",
        "character",
        character_app,
        ["create", "--project-id", PID, "--name", "角色甲", "--role-rank", "minor"],
        "post",
        "background",
        "--background",
        {"id": str(uuid.uuid4()), "name": "角色甲", "background": ""},
    ),
    Case(
        "character-update",
        "character",
        character_app,
        ["update", "--id", CHID],
        "patch",
        "background",
        "--background",
        {"id": CHID, "name": "角色甲", "background": ""},
    ),
]

CASE_IDS = [c.id for c in CASES]


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 起无 mix_stderr，默认混合输出）。"""
    return CliRunner()


@contextmanager
def _mock_kernel(module: str):
    """Mock `inkflow.cli.commands.<module>` 命名空间的 ensure_kernel + InkFlowHTTPClient。

    CLI 恒经 HTTP（Issue #169）：断言「落库」= 断言 HTTP `post` / `patch` 的 json body。
    """
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
            f"inkflow.cli.commands.{module}.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(f"inkflow.cli.commands.{module}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _write_utf8(tmp_path, name: str, text: str) -> str:
    """以**显式 UTF-8** 写临时文件，返回路径字符串（禁止用仓库内文件作 fixture）。"""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _body_of(mock_client, method: str) -> dict[str, Any]:
    """取出 mock client 最近一次 <method> 调用的 json body。"""
    call = getattr(mock_client, method).call_args
    assert call is not None, f"HTTP {method} 未被调用"
    return call.kwargs["json"]


# ---------------------------------------------------------------------------
# N1 — 文件内容原样落库（中文 + 换行，无乱码）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_content_file_persists_verbatim(cli_runner, tmp_path, case):
    """`--content-file <utf8 中文文件>` → 目标字段逐字符等于文件内容。"""
    body_path = _write_utf8(tmp_path, "body.md", FILE_BODY)
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*case.base, "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    payload = _body_of(client, case.method)
    assert payload[case.field] == FILE_BODY
    # 乱码（Unicode replacement char / 典型 GBK 误解码形态）不得出现
    assert "\ufffd" not in payload[case.field]


# ---------------------------------------------------------------------------
# N4 — 长正文（> 32KB，含换行）走文件通道成功
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_content_file_long_body_persists(cli_runner, tmp_path, case):
    """文件含换行长正文（> 32KB）→ 成功且逐字符落库（内联传参受命令行长度限制）。"""
    assert len(LONG_BODY.encode("utf-8")) > 32 * 1024
    body_path = _write_utf8(tmp_path, "long.md", LONG_BODY)
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*case.base, "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    payload = _body_of(client, case.method)
    assert payload[case.field] == LONG_BODY
    assert payload[case.field].count("\n") == LONG_BODY.count("\n")


# ---------------------------------------------------------------------------
# N2 — 互斥：内联正文参数 与 --content-file 同传 → 退出码 2 + 明确文案 + 不写入
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_inline_and_content_file_are_mutually_exclusive(cli_runner, tmp_path, case):
    """同传 → 退出码 2 + 「不能同时使用」文案；**不发生写入**（HTTP 未被调用）。"""
    body_path = _write_utf8(tmp_path, "body.md", FILE_BODY)
    with _mock_kernel(case.module) as client:
        result = cli_runner.invoke(
            case.app,
            [*case.base, case.inline_flag, INLINE_BODY, "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 2, result.output
        assert "不能同时使用" in result.output, result.output
        getattr(client, case.method).assert_not_called()


# ---------------------------------------------------------------------------
# N3 — 文件缺失/不可读 → VALIDATION_ERROR（退出码 1）+ 可读消息，非栈回溯
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_missing_content_file_reports_validation_error(cli_runner, tmp_path, case):
    """`--content-file` 指向不存在的文件 → 退出码 1 + VALIDATION_ERROR 错误信封。"""
    missing = str(tmp_path / "no-such-body.md")
    with _mock_kernel(case.module) as client:
        result = cli_runner.invoke(
            case.app,
            [*case.base, "--content-file", missing],
            obj=CliContext(json_output=True),
        )

        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output, result.output
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "VALIDATION_ERROR"
        assert envelope["error"]["message"], "错误消息不得为空"
        getattr(client, case.method).assert_not_called()


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.id in ("world-create", "chapter-update")],
    ids=["world", "chapter"],
)
def test_missing_content_file_human_mode_message(cli_runner, tmp_path, case):
    """人类模式：文件缺失 → 退出码 1 + stderr 可读文案（非栈回溯）。"""
    missing = str(tmp_path / "no-such-body.md")
    with _mock_kernel(case.module):
        result = cli_runner.invoke(
            case.app,
            [*case.base, "--content-file", missing],
            obj=CliContext(json_output=False),
        )

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output, result.output
    assert "no-such-body.md" in result.output, result.output


# ---------------------------------------------------------------------------
# N5 / N6 — 负例守卫：既有内联路径与 --json 信封不回归
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_inline_only_path_unchanged(cli_runner, case):
    """仅传内联正文（无 --content-file）→ 目标字段 == 内联值 + 信封结构不变（既有行为不回归）。"""
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*case.base, case.inline_flag, INLINE_BODY],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"ok", "data"}
    assert envelope["ok"] is True
    payload = _body_of(client, case.method)
    assert payload[case.field] == INLINE_BODY


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_json_envelope_unchanged(cli_runner, tmp_path, case):
    """`--json` 成功信封 `{"ok": true, "data": ...}` 不因新增参数而改变。"""
    body_path = _write_utf8(tmp_path, "body.md", FILE_BODY)
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*case.base, "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"ok", "data"}
    assert envelope["ok"] is True
    assert envelope["data"]["id"] == case.stub["id"]
