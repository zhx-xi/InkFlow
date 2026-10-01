"""#1430 方案 A：`inkflow book run --force/--confirm-overwrite` CLI 契约（RED→GREEN）。

权威来源：issue #1430 实现清单第 4 条 + 本单标题（`book run --force`）。

契约（本契约冻结）
==================

- `inkflow book run <plan_id> --force --confirm-overwrite` → POST
  `/agent/books/runs`，body 在既有 `writing_plan_id`（可选 `limits`）之上追加
  `force: true` / `confirm_overwrite: true`。
- **CLI 只做透传，不做本地判定**：双条件是**服务层不变量**（防自动化链路静默带
  force 必须由服务端把住）；只给 `--force` 时 CLI 照样原样发出去，由 API 回 422
  → CLI 走既有错误信封（❌ + exit 1）。
- **非 force 路径 body 逐字不变**：不带 flag 时 body 仍是
  `{"writing_plan_id": ...}`（既有 call-shape 契约断言零改动）。
- **备份落点随输出可见**：响应含 `overwrite` 块时，人类输出必须点明备份落点
  `chapters.previous_content` 与待备份章数（不做静默备份）。

RED 形态：`book run` 无 `--force` / `--confirm-overwrite` 选项 → typer 报
`No such option` + exit 2 → 各用例 `assert result.exit_code == 0` 干净 FAILED。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.cli.test_book_cmd import (  # 复用既有 CLI 契约测试装置（同目录共享）
    _invoke,
    _strip_ansi,
)

_BOOK_MOD = "inkflow.cli.commands.book_cmd"
_BACKUP_TARGET = "chapters.previous_content"
_DOUBLE_CONDITION_DETAIL = "force 与 confirm_overwrite 必须同时提供"


@pytest.fixture
def fake_http_client():
    """本地自包含副本：patch book_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client。

    （不从兄弟测试模块导入 fixture —— 导入名与函数形参同名会触发 ruff F811。）
    """
    fake_handle = SimpleNamespace(
        port=38292,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(f"{_BOOK_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{_BOOK_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_book_run_force_with_confirm_forwarded(fake_http_client):
    """--force + --confirm-overwrite → body 带上两位（双条件透传）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "running"}

    result = _invoke("run", "plan-1", "--force", "--confirm-overwrite")

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once_with(
        "/agent/books/runs",
        json={"writing_plan_id": "plan-1", "force": True, "confirm_overwrite": True},
    )


def test_book_run_force_only_is_forwarded_without_local_judgement(fake_http_client):
    """只给 --force 也照原样发出（不本地判定，由服务端 422 兜底）。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "running"}

    result = _invoke("run", "plan-1", "--force")

    assert result.exit_code == 0
    body = fake_http_client.post.await_args.kwargs["json"]
    assert body == {"writing_plan_id": "plan-1", "force": True}
    assert "confirm_overwrite" not in body


def test_book_run_without_flags_body_unchanged(fake_http_client):
    """非 force 路径零变化：body 仍只有 writing_plan_id。"""
    fake_http_client.post.return_value = {"run_id": "run-1", "status": "running"}

    result = _invoke("run", "plan-1")

    assert result.exit_code == 0
    fake_http_client.post.assert_awaited_once_with(
        "/agent/books/runs",
        json={"writing_plan_id": "plan-1"},
    )


def test_book_run_force_renders_backup_landing(fake_http_client):
    """备份落点随输出可见：人类输出点明备份列与待备份章数。"""
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "overwrite": {
            "forced": True,
            "backup_target": _BACKUP_TARGET,
            "chapters_to_backup": 2,
        },
    }

    result = _invoke("run", "plan-1", "--force", "--confirm-overwrite")

    assert result.exit_code == 0
    out = _strip_ansi(result.stdout)
    assert _BACKUP_TARGET in out
    assert "2" in out


def test_book_run_force_json_envelope_carries_overwrite(fake_http_client):
    """--json 信封原样透传 overwrite 块（GUI/脚本据此定位备份）。"""
    fake_http_client.post.return_value = {
        "run_id": "run-1",
        "status": "running",
        "overwrite": {
            "forced": True,
            "backup_target": _BACKUP_TARGET,
            "chapters_to_backup": 0,
        },
    }

    result = _invoke("run", "plan-1", "--force", "--confirm-overwrite", "--json")

    assert result.exit_code == 0
    body = json.loads(_strip_ansi(result.stdout))
    assert body["ok"] is True
    assert body["data"]["overwrite"]["backup_target"] == _BACKUP_TARGET


def test_book_run_force_only_422_exit_1(fake_http_client):
    """服务端双条件拒绝（422）→ CLI 错误信封 + exit 1（不假装成功）。"""
    from inkflow.infrastructure.http import HttpApiError

    fake_http_client.post.side_effect = HttpApiError(
        422, _DOUBLE_CONDITION_DETAIL, "VALIDATION_ERROR"
    )

    result = _invoke("run", "plan-1", "--force")

    assert result.exit_code == 1
    err = _strip_ansi(result.stderr)
    assert "❌" in err
    assert "confirm_overwrite" in err
