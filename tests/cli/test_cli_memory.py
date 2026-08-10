"""F28 M6 CLI RED 契约测试 — inkflow memory list/remove/stats（spec §4.1）.

整组 RED（规则 1n）: memory_cmd 模块不存在 → 顶部
from inkflow.cli.commands.memory_cmd import app → 收集期 ModuleNotFoundError
（collected 0 items / exit 2）。GREEN 后模块落地，本文件自动收集并直测。

══════════════════════════════════════════════════════════════════════════
HTTP 契约（父侧定稿，实现者以本文件为准）:
- memory list → GET /agent/preferences（params: project_id[, category]）
  → 200: {"items": [ProjectPreference dict], "total": N}
- memory remove <preference_id> → DELETE /agent/preferences/{preference_id}
  → 200: {"preference_id": "<id>", "deleted": true}
- memory stats → GET /agent/memory/stats（params: project_id）
  → 200: {"project_id", "agentic": {...}, "learned_preferences",
          "baseline_ref": "docs/agent-baseline-2026-08-10.md"}
- 信封: --json → {"ok": true, "data": <API 响应原样>}（镜像 agent_cmd.
  _print_json_envelope）
- 错误: HttpApiError → stderr「❌ {detail}」+ 退出码 1；KernelStartupError →
  「❌ 内核启动失败: ...」+ 退出码 1
══════════════════════════════════════════════════════════════════════════

人类模式输出（spec §4.1 逐字）:
- list: 每行「[addressing] 称呼主角为林晚 (confidence 0.67, ×2)」
- remove 成功: 「✅ 已删除偏好（下次生成立即停止注入）」
- stats: 修改率/重新生成率 + 基线对照提示（含 baseline_ref 路径）

恒 HTTP（F38）: 全部经 ensure_kernel() + InkFlowHTTPClient（patch memory_cmd
模块命名空间；fixture 覆盖 __aenter__/__aexit__——镜像 test_cli_agent_draft.py）。
每个 invoke 必带 obj=CliContext(json_output=...)：直调 memory_cmd.app 无根
callback 设 ctx.obj（根 callback 在 inkflow 根 app 上）。

RED 预期: 收集期 ModuleNotFoundError（collected 0 items / exit 2）。

asyncio 模式: 本 venv 实测 asyncio: mode=Mode.AUTO（pyproject
asyncio_mode = "auto" 生效）；本文件全部同步用例（CliRunner 轨）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.memory_cmd import app
from inkflow.cli.context import CliContext

runner = CliRunner()

MEMORY_MOD = "inkflow.cli.commands.memory_cmd"

PROJECT_ID = str(uuid.uuid4())
PREFERENCE_ID = str(uuid.uuid4())
UPDATED_PATTERN = "称呼主角为林晚"


def _pref_dict(**overrides) -> dict:
    """ProjectPreference dict（spec §3.2 字段口径）。"""
    pref = {
        "id": PREFERENCE_ID,
        "project_id": PROJECT_ID,
        "category": "addressing",
        "pattern": UPDATED_PATTERN,
        "value": "林晚",
        "confidence": 0.67,
        "count": 2,
        "source_events": ["evt-0001", "evt-0002"],
        "created_at": "2026-08-11T10:00:00",
        "updated_at": "2026-08-11T10:00:00",
    }
    pref.update(overrides)
    return pref


def _stats_payload(**overrides) -> dict:
    """memory/stats 响应口径（spec §3.2 示例逐字段）。"""
    stats = {
        "project_id": PROJECT_ID,
        "agentic": {
            "chapters": 5,
            "direct_confirms": 2,
            "avg_diff_chars": 320,
            "modify_rate": 0.6,
            "regenerate_rate": 0.2,
        },
        "learned_preferences": 3,
        "baseline_ref": "docs/agent-baseline-2026-08-10.md",
    }
    stats.update(overrides)
    return stats


def _invoke(*args: str):
    """memory 命令调用（obj=CliContext 必带；--json 与 obj.json_output 同步）。"""
    return runner.invoke(
        app, list(args), obj=CliContext(json_output=("--json" in args))
    )


@pytest.fixture
def fake_http_client():
    """Patch memory_cmd 内 ensure_kernel + InkFlowHTTPClient → fake client 实例.

    fixture 覆盖 __aenter__/__aexit__（镜像 test_cli_agent_draft.py）；client
    方法（get/delete）为裸 AsyncMock child，各用例显式设 return_value。
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
        patch(f"{MEMORY_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{MEMORY_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError（lazy import——F38 纪律，RED 阶段不触达）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


class TestMemoryList:
    """inkflow memory list — 项目已学偏好列表。"""

    def test_list_human(self, fake_http_client):
        """list 人类模式: GET /agent/preferences（params 正确）+ 每行偏好格式。"""
        fake_http_client.get.return_value = {
            "items": [
                _pref_dict(),
                _pref_dict(id=str(uuid.uuid4()), category="style_word"),
            ],
            "total": 2,
        }
        result = _invoke("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        call = fake_http_client.get.await_args
        assert call.args[0] == "/agent/preferences"
        assert call.kwargs["params"]["project_id"] == PROJECT_ID
        assert "[addressing] 称呼主角为林晚 (confidence 0.67, ×2)" in result.stdout
        assert "[style_word]" in result.stdout

    def test_list_json(self, fake_http_client):
        """list --json: stdout 信封 == API 响应原样（{"ok": true, "data": ...}）。"""
        payload = {"items": [_pref_dict()], "total": 1}
        fake_http_client.get.return_value = payload
        result = _invoke("list", "--project-id", PROJECT_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}

    def test_list_category_filter(self, fake_http_client):
        """list --category addressing: category 参数透传（params 含 category）。"""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = _invoke("list", "--project-id", PROJECT_ID, "--category", "addressing")
        assert result.exit_code == 0
        assert (
            fake_http_client.get.await_args.kwargs["params"]["category"] == "addressing"
        )


class TestMemoryRemove:
    """inkflow memory remove — 删除偏好（立即停止注入）。"""

    def test_remove_human(self, fake_http_client):
        """remove 人类模式: DELETE /agent/preferences/{id} + 成功文案。"""
        fake_http_client.delete.return_value = {
            "preference_id": PREFERENCE_ID,
            "deleted": True,
        }
        result = _invoke("remove", PREFERENCE_ID)
        assert result.exit_code == 0
        call = fake_http_client.delete.await_args
        assert call.args[0] == f"/agent/preferences/{PREFERENCE_ID}"
        assert "✅ 已删除偏好（下次生成立即停止注入）" in result.stdout

    def test_remove_json(self, fake_http_client):
        """remove --json: stdout 信封 == API 响应原样。"""
        payload = {"preference_id": PREFERENCE_ID, "deleted": True}
        fake_http_client.delete.return_value = payload
        result = _invoke("remove", PREFERENCE_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}


class TestMemoryStats:
    """inkflow memory stats — 修改率统计（验收判据①对照机制）。"""

    def test_stats_human(self, fake_http_client):
        """stats 人类模式: 修改率/重新生成率 + 基线对照提示（baseline_ref）。"""
        fake_http_client.get.return_value = _stats_payload()
        result = _invoke("stats", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        call = fake_http_client.get.await_args
        assert call.args[0] == "/agent/memory/stats"
        assert call.kwargs["params"]["project_id"] == PROJECT_ID
        assert "修改率" in result.stdout
        assert "重新生成率" in result.stdout
        assert "docs/agent-baseline-2026-08-10.md" in result.stdout

    def test_stats_json(self, fake_http_client):
        """stats --json: stdout 信封 == API 响应原样。"""
        payload = _stats_payload()
        fake_http_client.get.return_value = payload
        result = _invoke("stats", "--project-id", PROJECT_ID, "--json")
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"ok": True, "data": payload}


class TestMemoryErrors:
    """memory 命令错误映射（F38 §5.3）: HttpApiError → ❌ stderr + exit 1。"""

    def test_list_http_404(self, fake_http_client):
        """list 404（偏好不存在）→ stderr ❌ + 退出码 1。"""
        fake_http_client.get.side_effect = _http_err(404, "偏好不存在")
        result = _invoke("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 1
        assert "❌ 偏好不存在" in result.stderr

    def test_remove_http_404(self, fake_http_client):
        """remove 404（偏好不存在）→ stderr ❌ + 退出码 1。"""
        fake_http_client.delete.side_effect = _http_err(404, "偏好不存在")
        result = _invoke("remove", PREFERENCE_ID)
        assert result.exit_code == 1
        assert "❌ 偏好不存在" in result.stderr

    def test_stats_kernel_startup_error(self, fake_http_client):
        """ensure_kernel 失败 → stderr ❌ 内核启动失败 + 退出码 1。"""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            f"{MEMORY_MOD}.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = _invoke("stats", "--project-id", PROJECT_ID)
        assert result.exit_code == 1
        assert "❌ 内核启动失败: 启动超时" in result.stderr


class TestMemoryCoverageGaps:
    """QA 补测（2026-08-11，覆盖缺口闭合——防御分支与 N/A 渲染，规则 1j 形态）."""

    def test_list_none_data_early_return(self, fake_http_client):
        """list 响应 None（防御分支）→ 人类模式提前返回不崩."""
        fake_http_client.get.return_value = None
        result = _invoke("list", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        assert result.stdout == ""

    def test_remove_none_data_early_return(self, fake_http_client):
        """remove 响应 None（防御分支）→ 提前返回不崩."""
        fake_http_client.delete.return_value = None
        result = _invoke("remove", PREFERENCE_ID)
        assert result.exit_code == 0
        assert result.stdout == ""

    def test_stats_none_data_early_return(self, fake_http_client):
        """stats 响应 None（防御分支）→ 提前返回不崩."""
        fake_http_client.get.return_value = None
        result = _invoke("stats", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        assert result.stdout == ""

    def test_stats_na_rendering(self, fake_http_client):
        """stats 人类模式缺 modify_rate/regenerate_rate/baseline_ref → N/A 输出."""
        fake_http_client.get.return_value = _stats_payload(
            agentic={"chapters": 0, "direct_confirms": 0, "avg_diff_chars": 0},
            baseline_ref=None,
        )
        result = _invoke("stats", "--project-id", PROJECT_ID)
        assert result.exit_code == 0
        assert "N/A" in result.stdout
        assert "基线对照" in result.stdout
