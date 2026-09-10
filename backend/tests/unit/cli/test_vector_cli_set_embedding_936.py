"""#936 C 项 RED 契约（CLI）：`inkflow vector set-embedding` 命令。

背景（#936 spec §4.1）：
`PUT /api/v1/vector/embedding-model` 端点已存在（`extractions.py:184`），
但 CLI `vector` group 只有 status/reindex/retrieve 三个命令——「设为激活
embedding 模型」在 CLI 侧**无暴露**（issue C 项权衡点 5）。

契约：
```
inkflow vector set-embedding --provider <name> --model-id <id> [--force] [--json]
```
- 成功 → 退出码 0 + 人类可读文案；`--json` → F7 信封 `{"ok":true,"data":{...}}`
- `--force` → URL 带 `force=true`（透传门禁逃生门）
- 404 → `NOT_FOUND`；422 → `VALIDATION_ERROR`（复用 `_run` + `map_http_error`）

Mock 策略（镜像 tests/unit/cli/test_cli_character_gaps.py）：
patch `inkflow.cli.commands.vector.ensure_kernel` + `InkFlowHTTPClient`。

RED 形态：命令未注册 → CliRunner 退出码 2（No such command）→ 断言 FAIL。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.app import app
from inkflow.infrastructure.http import HttpApiError


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（镜像本仓既有 CLI 测试模式）。"""
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
            "inkflow.cli.commands.vector.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.vector.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.put = AsyncMock(return_value={"ok": True, "provider": "zhipu",
                                                    "model_id": "embedding-3"})
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestSetEmbeddingCommand:
    """`vector set-embedding` 命令契约。"""

    def test_r1_command_registered_and_succeeds(self, cli_runner, fake_http_client) -> None:
        """【R】命令存在 + 成功 → 退出码 0 + 调用 PUT 端点。

        RED 形态：命令未注册 → 退出码 2（No such command 'set-embedding'）。
        """
        result = cli_runner.invoke(
            app,
            ["vector", "set-embedding", "--provider", "zhipu", "--model-id", "embedding-3"],
        )

        assert result.exit_code == 0, (
            f"set-embedding 命令须可用（exit={result.exit_code}）：{result.output}"
        )
        fake_http_client.put.assert_awaited_once()
        path = fake_http_client.put.await_args.args[0]
        assert path == "/vector/embedding-model", f"须调用 PUT /vector/embedding-model，实际 {path}"

    def test_r2_payload_shape(self, cli_runner, fake_http_client) -> None:
        """【R】请求体为 {provider, model_id}。"""
        cli_runner.invoke(
            app,
            ["vector", "set-embedding", "--provider", "zhipu", "--model-id", "embedding-3"],
        )

        kwargs = fake_http_client.put.await_args.kwargs
        payload = kwargs.get("json") or kwargs.get("data")
        assert payload == {"provider": "zhipu", "model_id": "embedding-3"}, (
            f"请求体形状契约，实际 {payload!r}"
        )

    def test_r3_force_passed_through(self, cli_runner, fake_http_client) -> None:
        """【R】`--force` → 请求带 force=true（门禁逃生门透传）。"""
        cli_runner.invoke(
            app,
            ["vector", "set-embedding", "--provider", "zhipu", "--model-id", "embedding-3",
             "--force"],
        )

        call_repr = repr(fake_http_client.put.await_args)
        assert "force" in call_repr and "true" in call_repr.lower(), (
            f"--force 须透传 force=true，实际调用 {call_repr}"
        )

    def test_g1_no_force_by_default(self, cli_runner, fake_http_client) -> None:
        """【G】护栏：未传 --force → 请求不含 force=true。"""
        cli_runner.invoke(
            app,
            ["vector", "set-embedding", "--provider", "zhipu", "--model-id", "embedding-3"],
        )

        call_repr = repr(fake_http_client.put.await_args)
        assert "force=true" not in call_repr, "默认不得带 force=true（门禁须默认生效）"

    def test_r4_json_envelope(self, cli_runner, fake_http_client) -> None:
        """【R】`--json` → F7 信封 {"ok": true, "data": {...}}。"""
        result = cli_runner.invoke(
            app,
            ["--json", "vector", "set-embedding", "--provider", "zhipu",
             "--model-id", "embedding-3"],
        )

        assert result.exit_code == 0
        assert '"ok": true' in result.output or '"ok":true' in result.output, (
            f"--json 须输出 F7 信封，实际 {result.output!r}"
        )

    def test_r5_missing_option_exit_2(self, cli_runner) -> None:
        """【R】缺 --model-id → 退出码 2（Typer 参数校验）。"""
        result = cli_runner.invoke(app, ["vector", "set-embedding", "--provider", "zhipu"])

        assert result.exit_code == 2, f"缺必填参数须退出码 2，实际 {result.exit_code}"

    def test_r6_404_maps_to_not_found(self, cli_runner) -> None:
        """【R】HTTP 404 → F7 错误码 NOT_FOUND + 退出码 1。"""
        fake_handle = SimpleNamespace(port=38291, token="t", pid=1, version="0.1.0",
                                      started_at="", reused=True)
        with (
            patch("inkflow.cli.commands.vector.ensure_kernel",
                  AsyncMock(return_value=fake_handle)),
            patch("inkflow.cli.commands.vector.InkFlowHTTPClient", autospec=True) as mock_cls,
        ):
            mock_instance = AsyncMock()
            mock_instance.put = AsyncMock(
                side_effect=HttpApiError(404, "Provider 不存在", None)
            )
            mock_cls.return_value = mock_instance
            result = cli_runner.invoke(
                app,
                ["--json", "vector", "set-embedding", "--provider", "ghost",
                 "--model-id", "embedding-3"],
            )

        assert result.exit_code == 1
        assert "NOT_FOUND" in result.output, f"404 须映射 NOT_FOUND，实际 {result.output!r}"

    def test_r7_422_maps_to_validation_error(self, cli_runner) -> None:
        """【R】HTTP 422（门禁拒绝）→ F7 错误码 VALIDATION_ERROR。"""
        fake_handle = SimpleNamespace(port=38291, token="t", pid=1, version="0.1.0",
                                      started_at="", reused=True)
        with (
            patch("inkflow.cli.commands.vector.ensure_kernel",
                  AsyncMock(return_value=fake_handle)),
            patch("inkflow.cli.commands.vector.InkFlowHTTPClient", autospec=True) as mock_cls,
        ):
            mock_instance = AsyncMock()
            mock_instance.put = AsyncMock(
                side_effect=HttpApiError(422, "embedding 探测失败：维度为 0", None)
            )
            mock_cls.return_value = mock_instance
            result = cli_runner.invoke(
                app,
                ["--json", "vector", "set-embedding", "--provider", "zhipu",
                 "--model-id", "embedding-3"],
            )

        assert result.exit_code == 1
        assert "VALIDATION_ERROR" in result.output, (
            f"422 须映射 VALIDATION_ERROR，实际 {result.output!r}"
        )
