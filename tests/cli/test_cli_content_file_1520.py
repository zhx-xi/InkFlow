"""#1520 `create`/`update` 系列 `--content-file` 正文双通道 —— 横向覆盖 RED 契约测试.

**spec 为唯一真相**（本文件断言全部由 spec 推导，不读实现）:

- `specs/f7-cli/spec.md` §4.0（正文双通道通用约定 · v1.3 横向覆盖）
- 各命令归属 spec 的 CLI 契约节：
  `specs/f11-outline/spec.md`（outline point / arc）·
  `specs/f9-character/spec.md`（character group / relate）·
  `specs/f13-foreshadowing/spec.md` · `specs/f12-timeline/spec.md` ·
  `specs/f24-session/spec.md` · `specs/f36-world-map/spec.md` ·
  `specs/f48-knowledge-graph/spec.md` · `specs/f42-agent-chain/spec.md`

**范围** = #1483 覆盖的四个实体级命令之外的**同形态**命令（19 条）:

- `outline point create|update` · `outline arc create|update`（`description`）
- `character group create|update` · `character relate`（`description`）
- `foreshadowing create|update`（`description`）
- `timeline create|update`（`description`）
- `session create|update`（`description`；与既有 `--context-file` **并存**，语义不同）
- `map create|update`（`description`）
- `knowledge relation add|update`（`description`）
- `agent template create|update`（`description`）

**断言族（每个命令同构，参数化）**:

- N1 文件原样落库: `--content-file <utf8 中文文件>` → 目标字段逐字符等于文件内容
  （无乱码）。RED 预期 FAIL（参数不存在 → click `No such option`）。
- N1b CRLF 归一: CRLF 文件 → 目标字段为 LF 归一形态（F7 §4.0 通用换行读取）。
- N2 互斥: 内联正文参数 与 `--content-file` 同传 → 退出码 2 + 「不能同时使用」文案，
  且**不发生写入**（HTTP 未被调用）。
- N3 文件缺失: `--content-file` 指向不存在文件 → 退出码 1 + `VALIDATION_ERROR`
  错误信封 + 可读消息（非栈回溯），且**不发生写入**。
- N4 负例守卫: 仅内联正文 → 目标字段 == 内联值 + 信封结构不变。当前 PASS（守住）。
- N5 `--json` 成功信封 `{"ok": true, "data": ...}` 不变。当前 PASS（守住）。

**「无正文参数（不需要）」负例**（本轨刻意不覆盖，参数面不得变）见
`tests/cli/test_cli_content_file_1520_scope.py`。

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

from inkflow.cli.commands.agent_cmd import template_app
from inkflow.cli.commands.character import app as character_app
from inkflow.cli.commands.character import group_app
from inkflow.cli.commands.foreshadowing import app as foreshadowing_app
from inkflow.cli.commands.knowledge_graph import relation_app
from inkflow.cli.commands.map import app as map_app
from inkflow.cli.commands.outline import arc_app, point_app
from inkflow.cli.commands.session import app as session_app
from inkflow.cli.commands.timeline import app as timeline_app
from inkflow.cli.context import CliContext
from inkflow.domain.models.session import (
    Session,
    SessionStatus,
    SessionType,
    SessionView,
)

PID = "3f2e1d4a-0000-4000-8000-000000000001"
SID = "3f2e1d4a-0000-4000-8000-000000000002"
OID = "3f2e1d4a-0000-4000-8000-000000000004"
AID = "3f2e1d4a-0000-4000-8000-000000000006"
PTID = "3f2e1d4a-0000-4000-8000-000000000007"
GID = "3f2e1d4a-0000-4000-8000-000000000008"
CH1 = "3f2e1d4a-0000-4000-8000-000000000009"
CH2 = "3f2e1d4a-0000-4000-8000-00000000000a"
FID = "3f2e1d4a-0000-4000-8000-00000000000b"
TID = "3f2e1d4a-0000-4000-8000-00000000000c"
MAPID = "3f2e1d4a-0000-4000-8000-00000000000d"
RID = "3f2e1d4a-0000-4000-8000-00000000000e"
LOCID = "3f2e1d4a-0000-4000-8000-00000000000f"
TPL_ID = "tpl-1520"

# 含中文 + 换行 + 首尾空白的正文：验证「原样落库」（不 strip、不转码）
FILE_BODY = "\n九幽宗·总纲\n\n天地灵气复苏，宗门林立。\n  第二行带前导空格。\n"
INLINE_BODY = "内联正文（负例守卫）"
CRLF_BODY = "\r\n".join(("甲", "乙", "丙"))
CRLF_EXPECTED = "甲\n乙\n丙"


def _session_stub(description: str = "续写第三章") -> dict[str, Any]:
    """合法 `Session` JSON（update 响应形态）。"""
    return Session(
        id=uuid.UUID(SID),
        session_type=SessionType.WRITING,
        status=SessionStatus.ACTIVE,
        project_id=uuid.UUID(PID),
        title="第三章续写",
        description=description,
        context={},
        result={},
        error="",
        started_at="2026-08-01T10:00:00Z",
        created_at="2026-08-01T10:00:00Z",
        updated_at="2026-08-01T10:00:00Z",
    ).model_dump(mode="json")


def _view_stub() -> dict[str, Any]:
    """合法 `SessionView` JSON（create 响应形态）。"""
    session = Session.model_validate(_session_stub())
    return SessionView(session=session, log_count=0, last_log=None).model_dump(mode="json")


def _png(tmp_path) -> str:
    """写一个扩展名合法的最小图片文件（`map create --image` 需求；内容不校验）。"""
    path = tmp_path / "map.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(path)


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
        *,
        body_kind: str = "json",
        extra_args: Any = None,
    ) -> None:
        self.id = case_id
        self.module = module
        self.app = app
        self.base = base
        self.method = method
        self.field = field
        self.inline_flag = inline_flag
        self.stub = stub
        self.body_kind = body_kind
        self.extra_args = extra_args


CASES = [
    # ── outline point / arc（同模块子实体） ──
    Case(
        "outline-point-create",
        "outline",
        point_app,
        ["create", "--outline-id", OID, "--name", "开端"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "name": "开端", "type": ""},
    ),
    Case(
        "outline-point-update",
        "outline",
        point_app,
        ["update", "--id", PTID],
        "patch",
        "description",
        "--description",
        {"id": PTID, "name": "开端", "type": ""},
    ),
    Case(
        "outline-arc-create",
        "outline",
        arc_app,
        ["create", "--project-id", PID, "--name", "成长弧"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "name": "成长弧"},
    ),
    Case(
        "outline-arc-update",
        "outline",
        arc_app,
        ["update", "--id", AID],
        "patch",
        "description",
        "--description",
        {"id": AID, "name": "成长弧"},
    ),
    # ── character group / relate ──
    Case(
        "character-group-create",
        "character",
        group_app,
        ["create", "--project-id", PID, "--name", "主角团"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "name": "主角团"},
    ),
    Case(
        "character-group-update",
        "character",
        group_app,
        ["update", "--id", GID],
        "patch",
        "description",
        "--description",
        {"id": GID, "name": "主角团"},
    ),
    Case(
        "character-relate",
        "character",
        character_app,
        ["relate", "--id", CH1, "--to", CH2, "--type", "盟友"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "relation_type": "盟友"},
    ),
    # ── foreshadowing ──
    Case(
        "foreshadowing-create",
        "foreshadowing",
        foreshadowing_app,
        ["create", "--project-id", PID, "--title", "断剑"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "title": "断剑", "priority": 50, "status": "open"},
    ),
    Case(
        "foreshadowing-update",
        "foreshadowing",
        foreshadowing_app,
        ["update", "--id", FID],
        "patch",
        "description",
        "--description",
        {"id": FID, "title": "断剑", "priority": 50, "status": "open"},
    ),
    # ── timeline ──
    Case(
        "timeline-create",
        "timeline",
        timeline_app,
        ["create", "--project-id", PID, "--title", "示例事件"],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "title": "示例事件", "narrative_position": 1},
    ),
    Case(
        "timeline-update",
        "timeline",
        timeline_app,
        ["update", "--id", TID],
        "patch",
        "description",
        "--description",
        {"id": TID, "title": "示例事件", "narrative_position": 1},
    ),
    # ── session（已有 --context-file，二者并存） ──
    Case(
        "session-create",
        "session",
        session_app,
        ["create", "--type", "writing", "--title", "第三章续写"],
        "post",
        "description",
        "--description",
        _view_stub(),
    ),
    Case(
        "session-update",
        "session",
        session_app,
        ["update", "--id", SID],
        "patch",
        "description",
        "--description",
        _session_stub(),
    ),
    # ── map（create 走 post_file：body 在 `data=` 而非 `json=`） ──
    Case(
        "map-create",
        "map",
        map_app,
        ["create", "--project-id", PID, "--name", "九幽城"],
        "post_file",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "name": "九幽城"},
        body_kind="file",
        extra_args=lambda tmp: ["--image", _png(tmp)],
    ),
    Case(
        "map-update",
        "map",
        map_app,
        ["update", MAPID],
        "patch",
        "description",
        "--description",
        {"id": MAPID, "name": "九幽城"},
    ),
    # ── knowledge relation ──
    Case(
        "knowledge-relation-add",
        "knowledge_graph",
        relation_app,
        [
            "add",
            PID,
            "--source-type",
            "character",
            "--source-id",
            CH1,
            "--target-type",
            "location",
            "--target-id",
            LOCID,
            "--relation-type",
            "师徒",
        ],
        "post",
        "description",
        "--description",
        {"id": str(uuid.uuid4()), "relation_type": "师徒"},
    ),
    Case(
        "knowledge-relation-update",
        "knowledge_graph",
        relation_app,
        ["update", RID],
        "patch",
        "description",
        "--description",
        {"id": RID, "relation_type": "师徒"},
    ),
    # ── agent template ──
    Case(
        "agent-template-create",
        "agent_cmd",
        template_app,
        ["create", "--name", "默认模板"],
        "post",
        "description",
        "--description",
        {"id": TPL_ID, "name": "默认模板"},
    ),
    Case(
        "agent-template-update",
        "agent_cmd",
        template_app,
        ["update", "--id", TPL_ID],
        "patch",
        "description",
        "--description",
        {"id": TPL_ID, "name": "默认模板"},
    ),
]

CASE_IDS = [c.id for c in CASES]

assert len(CASES) == 19, "横向覆盖清单应为 19 条命令（#1520）"


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 起无 mix_stderr，默认混合输出）。"""
    return CliRunner()


@contextmanager
def _mock_kernel(module: str):
    """Mock `inkflow.cli.commands.<module>` 命名空间的 ensure_kernel + InkFlowHTTPClient.

    CLI 恒经 HTTP（Issue #169）：断言「落库」= 断言 HTTP 请求体。
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


def _args(case: Case, tmp_path) -> list[str]:
    """基准参数（含 write 型命令的额外出参）。"""
    extra = case.extra_args(tmp_path) if case.extra_args is not None else []
    return [*case.base, *extra]


def _body_of(mock_client, case: Case) -> dict[str, Any]:
    """取出 mock client 最近一次调用的请求体（`json=` 或 `post_file` 的 `data=`）。"""
    call = getattr(mock_client, case.method).call_args
    assert call is not None, f"HTTP {case.method} 未被调用"
    key = "data" if case.body_kind == "file" else "json"
    return call.kwargs[key]


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
            [*_args(case, tmp_path), "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    payload = _body_of(client, case)
    assert payload[case.field] == FILE_BODY
    # 乱码（Unicode replacement char / 典型 GBK 误解码形态）不得出现
    assert "\ufffd" not in payload[case.field]


# ---------------------------------------------------------------------------
# N1b — CRLF 文件按通用换行读取归一为 LF（与既有文件通道一致）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_content_file_crlf_normalized(cli_runner, tmp_path, case):
    """CRLF 文件 → 目标字段 LF 归一（F7 §4.0 通用换行读取）。"""
    path = tmp_path / "body-crlf.txt"
    path.write_bytes(CRLF_BODY.encode("utf-8"))  # 字节级写入，避免文本模式改写行尾
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*_args(case, tmp_path), "--content-file", str(path)],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    payload = _body_of(client, case)
    assert payload[case.field] == CRLF_EXPECTED


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
            [
                *_args(case, tmp_path),
                case.inline_flag,
                INLINE_BODY,
                "--content-file",
                body_path,
            ],
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
            [*_args(case, tmp_path), "--content-file", missing],
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
    [c for c in CASES if c.id in ("foreshadowing-create", "timeline-update")],
    ids=["foreshadowing", "timeline"],
)
def test_missing_content_file_human_mode_message(cli_runner, tmp_path, case):
    """人类模式：文件缺失 → 退出码 1 + stderr 可读文案（非栈回溯）。"""
    missing = str(tmp_path / "no-such-body.md")
    with _mock_kernel(case.module):
        result = cli_runner.invoke(
            case.app,
            [*_args(case, tmp_path), "--content-file", missing],
            obj=CliContext(json_output=False),
        )

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output, result.output
    assert "no-such-body.md" in result.output, result.output


# ---------------------------------------------------------------------------
# N4 / N5 — 负例守卫：既有内联路径与 --json 信封不回归
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_inline_only_path_unchanged(cli_runner, tmp_path, case):
    """仅传内联正文（无 --content-file）→ 目标字段 == 内联值 + 信封结构不变。"""
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*_args(case, tmp_path), case.inline_flag, INLINE_BODY],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"ok", "data"}
    assert envelope["ok"] is True
    payload = _body_of(client, case)
    assert payload[case.field] == INLINE_BODY


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_json_envelope_unchanged(cli_runner, tmp_path, case):
    """`--json` 成功信封 `{"ok": true, "data": ...}` 不因新增参数而改变。"""
    body_path = _write_utf8(tmp_path, "body.md", FILE_BODY)
    with _mock_kernel(case.module) as client:
        getattr(client, case.method).return_value = case.stub
        result = cli_runner.invoke(
            case.app,
            [*_args(case, tmp_path), "--content-file", body_path],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"ok", "data"}
    assert envelope["ok"] is True
    assert "data" in envelope


# ---------------------------------------------------------------------------
# session 双通道并存：#context-file 不被 --content-file 吞并（语义不同）
# ---------------------------------------------------------------------------


def test_session_context_file_still_independent(cli_runner, tmp_path):
    """`session create --description-file` 之外的既有 `--context-file` 通道不受影响.

    `--content-file` 只接 `description`；`--context-file` 仍是 JSON 上下文快照通道。
    """
    ctx_path = tmp_path / "ctx.json"
    ctx_path.write_text(json.dumps({"chapter_id": "7b9c"}), encoding="utf-8")
    body_path = _write_utf8(tmp_path, "body.md", FILE_BODY)
    with _mock_kernel("session") as client:
        client.post.return_value = _view_stub()
        result = cli_runner.invoke(
            session_app,
            [
                "create",
                "--type",
                "writing",
                "--title",
                "第三章续写",
                "--content-file",
                body_path,
                "--context-file",
                str(ctx_path),
            ],
            obj=CliContext(json_output=True),
        )

    assert result.exit_code == 0, result.output
    payload = client.post.call_args.kwargs["json"]
    assert payload["description"] == FILE_BODY
    assert payload["context"] == {"chapter_id": "7b9c"}
