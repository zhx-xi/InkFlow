"""#1408 CLI 契约：`extract --type` 的 choices / 参数 help / 组 help 必须与枚举全集一致。

issue #1408 的核心是**三层口径不一致**：
- 组 help 写「6 种类型」（`backend/src/inkflow/cli/commands/extract.py` 组描述）
- `--type` 参数 help 只列 6 个值
- 但 choices 由 `ExtractionType` 枚举自动派生 → 实际接受 **7** 个（含 `knowledge_relation`）

用户因此只能靠猜：`extract run --type knowledge_relation` 被 CLI 接受，却被内核
422「不支持的提取类型」（服务层注册表当时只有 6 槽）。

本文件是**防再次漂移的闸门**（本单重点，不只是补一行实现）：
枚举新增成员而 CLI help/组描述未跟进 → 直接 FAIL；`--type` 被换成不含全集的窄枚举
（方案 B 若被采用）→ choices 断言同样 FAIL，迫使显式改契约。

依据: specs/f14-extraction/spec.md §4.1 + issue #1408。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.extract import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.extraction import ExtractionType

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")

ENUM_VALUES = [t.value for t in ExtractionType]


@pytest.fixture
def cli_runner() -> CliRunner:
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）."""
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
            "inkflow.cli.commands.extract.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.extract.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


# ── 契约（枚举 ↔ CLI 面）────────────────────────────────────────


def _extract_commands():
    """取 extract 组的 click 命令与 run 子命令（Typer → click 派生形态）."""
    from typer.main import get_command

    group = get_command(app)
    return group, group.commands["run"]


def _type_param(run_cmd):
    """取 run 命令的 `--type` 参数对象."""
    return next(p for p in run_cmd.params if p.name == "type")


def test_type_choices_cover_every_enum_value() -> None:
    """`--type` 的可选值集合 == ExtractionType 全集（窄化或漏接 → FAIL）."""
    _, run_cmd = _extract_commands()

    choices = set(_type_param(run_cmd).type.choices)

    assert choices == set(ENUM_VALUES)


def test_type_help_lists_every_enum_value() -> None:
    """`--type` 参数 help 的类型清单必须包含枚举全集（枚举扩张未跟进 → FAIL）."""
    _, run_cmd = _extract_commands()

    help_text = _type_param(run_cmd).help or ""
    missing = [value for value in ENUM_VALUES if value not in help_text]

    assert not missing, f"--type help 未列出枚举值: {missing}（help 应写: {'/'.join(ENUM_VALUES)}）"


def test_group_help_declares_enum_count() -> None:
    """组 help 声明的类型数量必须等于枚举成员数（「6 种类型」vs 7 个值 = #1408 症状）."""
    group, _ = _extract_commands()

    assert f"{len(ENUM_VALUES)} 种类型" in (group.help or "")


def test_run_doc_declares_enum_count() -> None:
    """`extract run` 命令帮助同样声明与枚举一致的类型数量."""
    _, run_cmd = _extract_commands()

    assert f"{len(ENUM_VALUES)} 种类型" in (run_cmd.help or "")


# ── 行为（CLI 不改写项目级类型的参数语义）─────────────────────


def test_run_knowledge_relation_without_source_json(cli_runner, fake_http_client) -> None:
    """`run --type knowledge_relation` 无源参数 → 原样透传给 /extract（项目级提取）."""
    fake_http_client.post.return_value = {
        "type": "knowledge_relation",
        "status": "success",
        "skipped_reason": None,
        "processed_sources": 1,
        "skipped_sources": 0,
        "created": 5,
        "updated": 0,
        "warnings": [],
        "model": None,
        "indexed": False,
        "detail": {},
    }

    result = cli_runner.invoke(
        app,
        ["run", "--project-id", str(PID), "--type", "knowledge_relation"],
        obj=CliContext(json_output=True),
    )

    assert result.exit_code == 0, result.output
    body: dict = fake_http_client.post.await_args.kwargs["json"]
    assert fake_http_client.post.await_args.args[0] == "/extract"
    assert body["type"] == "knowledge_relation"
    assert body["text"] is None
    assert body["chapter_ids"] is None
    assert body["index"] is False
    assert json.loads(result.stdout)["data"]["created"] == 5


def test_run_knowledge_relation_human_summary(cli_runner, fake_http_client) -> None:
    """人类模式摘要按统一信封渲染（零 LLM → 不出现模型信息）."""
    fake_http_client.post.return_value = {
        "type": "knowledge_relation",
        "status": "success",
        "skipped_reason": None,
        "processed_sources": 1,
        "skipped_sources": 0,
        "created": 5,
        "updated": 0,
        "warnings": [],
        "model": None,
        "indexed": False,
        "detail": {},
    }

    result = cli_runner.invoke(
        app,
        ["run", "--project-id", str(PID), "--type", "knowledge_relation"],
        obj=CliContext(json_output=False),
    )

    assert result.exit_code == 0
    assert "✅ 提取完成: knowledge_relation 处理 1 个源（跳过 0），新增 5 更新 0" in result.output
