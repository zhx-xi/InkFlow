"""#1475 CLI `agent run --pipeline` 三形态 —— RED 契约（spec f42 §4.1 / §13 M10）。

契约（HTTP 层，实现者以本文件为准）：

| `--pipeline` 取值 | 判别 | POST /agent/pipelines/execute body |
|---|---|---|
| `builtin:*` | 前缀 | `pipeline=<id>`，**不带** `stages` / `pipeline_config` |
| `<path>.yaml`（或存在的文件） | 后缀 / 存在 | `pipeline=<原值>` + `pipeline_config=<对象>` |
| 其余（role_key 序列，逗号分隔） | 兜底 | `pipeline=<原值>` + `stages=[<role_key>...]` |

失败面（CLI 本地，不发请求）：YAML 不存在 / 解析失败 / 结构非法 → stderr「❌ …」+ 退出码 1；
空 role 列表（如 `--pipeline ","`）→ 退出码 1。

RED 形态（实现前实测）：当前 `--pipeline "worldview,polisher"` 被当内置 id 查找 →
`未知管线模板: worldview,polisher`（422 → 退出码 1）；本文件 `stages` 断言全部 FAIL。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.__main__ import app

runner = CliRunner()

AGENT_MOD = "inkflow.cli.commands.agent_cmd"

PROJECT_ID = str(uuid.uuid4())

VALID_YAML = """name: 世界观润色链
description: 世界观校验 → 润色
stages:
  - id: worldview
    name: 世界观校验
    agent:
      id: worldview
      name: 世界观顾问
      system_prompt: 校验设定一致性
  - id: polisher
    name: 文笔润色
    agent:
      id: polisher
      name: 润色师
      system_prompt: 润色文笔
"""


@pytest.fixture
def fake_http_client():
    """Patch agent_cmd 的 ensure_kernel + InkFlowHTTPClient → fake client。"""
    fake_handle = SimpleNamespace(
        port=38291, token="t", pid=1, version="0.1.0", started_at="", reused=True
    )
    with (
        patch(f"{AGENT_MOD}.ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch(f"{AGENT_MOD}.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(
            return_value={
                "execution_id": "exec-1475",
                "pipeline": "builtin:write_chapter",
                "project_id": PROJECT_ID,
                "status": "pending",
                "created_at": "2026-10-07T10:00:00Z",
            }
        )
        mock_cls.return_value = mock_instance
        yield mock_instance


def _run(*extra: str):
    return runner.invoke(app, ["agent", "run", "--project-id", PROJECT_ID, *extra])


def _posted_body(fake_http_client) -> dict:
    """取出 POST /agent/pipelines/execute 的 json body（断言请求契约用）。"""
    call = fake_http_client.post.await_args
    assert call.args[0] == "/agent/pipelines/execute"
    return call.kwargs["json"]


class TestPipelineArgForms:
    """三形态判别（spec §4.1）。"""

    def test_role_list_sends_stages(self, fake_http_client) -> None:
        """形态 3：role_key 序列 → body 携带 stages（去空白、按序）。"""
        result = _run("--pipeline", "worldview, polisher")

        assert result.exit_code == 0
        body = _posted_body(fake_http_client)
        assert body["stages"] == ["worldview", "polisher"]
        assert "pipeline_config" not in body
        assert body["pipeline"] == "worldview, polisher"

    def test_single_role_is_single_stage(self, fake_http_client) -> None:
        """单 role_key（无逗号）同属形态 3 → stages 单元素。"""
        result = _run("--pipeline", "polisher")

        assert result.exit_code == 0
        assert _posted_body(fake_http_client)["stages"] == ["polisher"]

    def test_yaml_path_sends_pipeline_config(self, fake_http_client, tmp_path: Path) -> None:
        """形态 2：YAML 文件 → body 携带 pipeline_config（本地读取 + 校验）。"""
        yaml_path = tmp_path / "chain.yaml"
        yaml_path.write_text(VALID_YAML, encoding="utf-8")

        result = _run("--pipeline", str(yaml_path))

        assert result.exit_code == 0
        body = _posted_body(fake_http_client)
        assert "stages" not in body
        assert body["pipeline_config"]["name"] == "世界观润色链"
        assert [s["id"] for s in body["pipeline_config"]["stages"]] == ["worldview", "polisher"]
        assert body["pipeline_config"]["source"] == "yaml"

    @pytest.mark.parametrize(
        "value", ["builtin:write_auto", "builtin:write_continue", "builtin:chat"]
    )
    def test_builtin_id_sends_no_custom_payload(self, fake_http_client, value: str) -> None:
        """形态 1（含默认值）：内置 id 不带 stages / pipeline_config（零回归）。"""
        result = _run("--pipeline", value)

        assert result.exit_code == 0
        body = _posted_body(fake_http_client)
        assert body["pipeline"] == value
        assert "stages" not in body
        assert "pipeline_config" not in body

    def test_default_pipeline_unchanged(self, fake_http_client) -> None:
        """未传 --pipeline → 仍是 builtin:write_chapter（默认值零回归）。"""
        result = _run()

        assert result.exit_code == 0
        body = _posted_body(fake_http_client)
        assert body["pipeline"] == "builtin:write_chapter"
        assert "stages" not in body
        assert "pipeline_config" not in body

    def test_extensionless_existing_file_treated_as_yaml(
        self, fake_http_client, tmp_path: Path
    ) -> None:
        """存在的文件（无 .yaml 后缀）同属形态 2（is_file 分支）。"""
        path = tmp_path / "chain"
        path.write_text(VALID_YAML, encoding="utf-8")

        result = _run("--pipeline", str(path))

        assert result.exit_code == 0
        body = _posted_body(fake_http_client)
        assert body["pipeline_config"]["name"] == "世界观润色链"


class TestPipelineArgFailures:
    """本地失败面：不发请求 + 退出码 1（spec §4.1）。"""

    def test_missing_yaml_file_exits_1_without_request(
        self, fake_http_client, tmp_path: Path
    ) -> None:
        result = _run("--pipeline", str(tmp_path / "nope.yaml"))

        assert result.exit_code == 1
        assert "❌" in result.stderr
        fake_http_client.post.assert_not_awaited()

    def test_empty_role_list_exits_1_without_request(self, fake_http_client) -> None:
        result = _run("--pipeline", " , ")

        assert result.exit_code == 1
        assert "❌" in result.stderr
        fake_http_client.post.assert_not_awaited()

    def test_malformed_yaml_exits_1_without_request(self, fake_http_client, tmp_path: Path) -> None:
        """结构非法（缺 name/stages）→ 本地拒绝，不发请求。"""
        bad = tmp_path / "bad.yaml"
        bad.write_text("description: 只有描述\n", encoding="utf-8")

        result = _run("--pipeline", str(bad))

        assert result.exit_code == 1
        assert "❌" in result.stderr
        fake_http_client.post.assert_not_awaited()

    def test_unknown_role_surfaces_422(self, fake_http_client) -> None:
        """未知 role_key → 服务端 422 → stderr ❌ + 退出码 1（不吞错）。"""
        from inkflow.infrastructure.http import HttpApiError

        fake_http_client.post.side_effect = HttpApiError(
            status_code=422, detail="未知 stage 角色: ghost"
        )
        result = _run("--pipeline", "ghost", "--json")

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert "未知 stage 角色: ghost" in payload["error"]["message"]

    def test_yaml_syntax_error_exits_1_without_request(
        self, fake_http_client, tmp_path: Path
    ) -> None:
        """YAML 语法错误（YAMLError）→ 本地拒绝。"""
        bad = tmp_path / "broken.yaml"
        bad.write_text("name: [unclosed\n", encoding="utf-8")

        result = _run("--pipeline", str(bad))

        assert result.exit_code == 1
        assert "❌" in result.stderr
        fake_http_client.post.assert_not_awaited()

    def test_yaml_non_mapping_exits_1_without_request(
        self, fake_http_client, tmp_path: Path
    ) -> None:
        """YAML 顶层非映射（列表）→ TypeError 路径本地拒绝。"""
        bad = tmp_path / "list.yaml"
        bad.write_text("- a\n- b\n", encoding="utf-8")

        result = _run("--pipeline", str(bad))

        assert result.exit_code == 1
        assert "❌" in result.stderr
        fake_http_client.post.assert_not_awaited()
