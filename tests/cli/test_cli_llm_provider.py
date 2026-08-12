"""LLM Provider CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（HTTP JSON 响应）。

测试范围：#251 P1-A — inkflow llm provider list/get/create/update/delete/models、
llm test、llm key remove。provider 组为 HTTP 轨（镜像 test_cli_project_mock.py
F38 模式）；key remove 为本地同步轨（APIKeyManager.delete，镜像 test_cli_llm.py）。

HTTP 契约（实现者以本文件为准，#251 任务书 + provider_configs.py 5 端点）:
- list    → GET  /provider-configs            → {"items": [...], "total": N}
- get     → GET  /provider-configs/{id}       → 404 「Provider 不存在」
- create  → POST /provider-configs            → 201 完整响应（含 key_saved/models）
- update  → PATCH /provider-configs/{id}      → 完整响应（exclude_unset 浅合并）
- delete  → DELETE /provider-configs/{id}     → 204 空响应；内置 seed（openai/
  deepseek/zhipu/ollama）删除 → 409「内置 Provider 不可删除」
- models  → GET 现有 models → PATCH /provider-configs/{id} {models: 全量替换}
  （--add/--remove/--set-json 三互斥；--set-json 直发不先 GET）
- test    → POST /settings/llm/test           → {"ok": bool, "message": str}
- 路径一律相对 base_url（InkFlowHTTPClient base_url 已含 /api/v1，#246 教训）

── RED 形态说明 ────────────────────────────────────────────────
llm.py 当前为纯同步本地轨（无 ensure_kernel / InkFlowHTTPClient import），
patch 目标 inkflow.cli.commands.llm.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部 HTTP 用例 fixture setup AttributeError（同根因，预期 RED）；
key remove 用例 patch APIKeyManager（已存在）→ 命令缺失断言 FAIL。
"""

import json
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.context import CliContext


@pytest.fixture
def cli_runner():
    # click 8.4 / typer 0.27 已移除 mix_stderr 参数，默认混合输出
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    patch 目标 = 命令模块命名空间（GREEN 后命令模块 from-import 绑定自身）。
    RED 阶段 llm.py 无这些符号 → fixture setup AttributeError（预期形态）。
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
            "inkflow.cli.commands.llm.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.llm.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段不影响收集形态，仅用例体执行）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_provider(**overrides) -> dict:
    """构造测试用 Provider JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=1,
        name="deepseek",
        builtin_key="deepseek",
        base_url=None,
        default_model="deepseek-chat",
        models=[{"id": "deepseek-chat", "type": "chat", "roles": []}],
        max_retries=3,
        timeout=120,
        key_saved=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestProviderList:
    def test_list_json_envelope(self, cli_runner, fake_http_client):
        """llm provider list --json → 信封 + GET /provider-configs."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = {
            "items": [_make_provider()],
            "total": 1,
        }
        result = cli_runner.invoke(
            app, ["provider", "list"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["name"] == "deepseek"
        assert fake_http_client.get.await_args.args[0] == "/provider-configs"

    def test_list_human_mode(self, cli_runner, fake_http_client):
        """人类模式列出 provider."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = {
            "items": [_make_provider()],
            "total": 1,
        }
        result = cli_runner.invoke(
            app, ["provider", "list"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "deepseek" in result.output

    def test_list_empty_human(self, cli_runner, fake_http_client):
        """空列表人类模式."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app, ["provider", "list"], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "暂无" in result.output or "📭" in result.output


class TestProviderGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """llm provider get --id 1 → 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = _make_provider()
        result = cli_runner.invoke(
            app, ["provider", "get", "--id", "1"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "deepseek"
        assert fake_http_client.get.await_args.args[0] == "/provider-configs/1"

    def test_get_not_found(self, cli_runner, fake_http_client):
        """不存在 → NOT_FOUND 信封 + 退出码 1."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.side_effect = _http_error(404, "Provider 不存在")
        result = cli_runner.invoke(
            app, ["provider", "get", "--id", "999"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestProviderCreate:
    def test_create_json(self, cli_runner, fake_http_client):
        """创建 provider → POST /provider-configs + 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = _make_provider(id=2, name="custom")
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "create",
                "--name",
                "custom",
                "--base-url",
                "https://api.custom.dev/v1",
                "--default-model",
                "custom/model-x",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "custom"
        call = fake_http_client.post.await_args
        assert call.args[0] == "/provider-configs"
        body = call.kwargs["json"]
        assert body["name"] == "custom"
        assert body["base_url"] == "https://api.custom.dev/v1"

    def test_create_human(self, cli_runner, fake_http_client):
        """人类模式创建成功提示."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = _make_provider(id=2, name="custom")
        result = cli_runner.invoke(
            app,
            ["provider", "create", "--name", "custom"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "custom" in result.output

    def test_create_full_options(self, cli_runner, fake_http_client):
        """全可选参数（--max-retries/--timeout/--models-json）落入请求体."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = _make_provider(id=2, name="custom")
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "create",
                "--name",
                "custom",
                "--max-retries",
                "5",
                "--timeout",
                "30",
                "--models-json",
                '[{"id": "m1", "type": "chat", "roles": []}]',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["max_retries"] == 5
        assert body["timeout"] == 30
        assert body["models"] == [{"id": "m1", "type": "chat", "roles": []}]

    def test_create_invalid_models_json(self, cli_runner, fake_http_client):
        """--models-json 非法 JSON → VALIDATION_ERROR + 不调用 POST."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "create", "--name", "custom", "--models-json", "{bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "--models-json" in data["error"]["message"]
        fake_http_client.post.assert_not_awaited()

    def test_create_conflict_422(self, cli_runner, fake_http_client):
        """重名冲突 → VALIDATION_ERROR 信封（detail 透传）."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.side_effect = _http_error(422, "Provider 名称已存在")
        result = cli_runner.invoke(
            app,
            ["provider", "create", "--name", "deepseek"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "Provider 名称已存在" in data["error"]["message"]


class TestProviderUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """更新 provider → PATCH /provider-configs/{id} + 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.patch.return_value = _make_provider(timeout=60)
        result = cli_runner.invoke(
            app,
            ["provider", "update", "--id", "1", "--timeout", "60"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["timeout"] == 60
        call = fake_http_client.patch.await_args
        assert call.args[0] == "/provider-configs/1"
        assert call.kwargs["json"] == {"timeout": 60}

    def test_update_not_found(self, cli_runner, fake_http_client):
        """不存在 → NOT_FOUND."""
        from inkflow.cli.commands.llm import app

        fake_http_client.patch.side_effect = _http_error(404, "Provider 不存在")
        result = cli_runner.invoke(
            app,
            ["provider", "update", "--id", "999", "--timeout", "60"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_multiple_fields(self, cli_runner, fake_http_client):
        """多字段更新（--name/--base-url/--default-model/--max-retries）落入请求体."""
        from inkflow.cli.commands.llm import app

        fake_http_client.patch.return_value = _make_provider(name="renamed")
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "update",
                "--id",
                "1",
                "--name",
                "renamed",
                "--base-url",
                "https://new.example/v1",
                "--default-model",
                "new/model",
                "--max-retries",
                "7",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert body == {
            "name": "renamed",
            "base_url": "https://new.example/v1",
            "default_model": "new/model",
            "max_retries": 7,
        }

    def test_update_invalid_models_json(self, cli_runner, fake_http_client):
        """update --models-json 非法 JSON → VALIDATION_ERROR + 不调用 PATCH."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "update", "--id", "1", "--models-json", "{bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.patch.assert_not_awaited()


class TestProviderDelete:
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """--force 删除 → DELETE /provider-configs/{id} + {deleted: true} 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "5", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert fake_http_client.delete.await_args.args[0] == "/provider-configs/5"

    def test_delete_without_force_prompts(self, cli_runner, fake_http_client):
        """无 --force 交互确认，回答 n 应取消."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "5"],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_delete_json_without_force_rejected(self, cli_runner, fake_http_client):
        """--json + 无 --force → VALIDATION_ERROR 短路（服务不被调用）."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()

    def test_delete_builtin_seed_409(self, cli_runner, fake_http_client):
        """内置 seed 删除 → 409「内置 Provider 不可删除」→ INTERNAL_ERROR 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.delete.side_effect = _http_error(409, "内置 Provider 不可删除")
        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "1", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "内置 Provider 不可删除" in data["error"]["message"]

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """不存在 → NOT_FOUND."""
        from inkflow.cli.commands.llm import app

        fake_http_client.delete.side_effect = _http_error(404, "Provider 不存在")
        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "999", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"

    def test_delete_force_human(self, cli_runner, fake_http_client):
        """人类模式 --force 删除成功 → ✅ 输出."""
        from inkflow.cli.commands.llm import app

        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["provider", "delete", "--id", "5", "--force"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output


class TestProviderModels:
    _EXISTING_MODELS: ClassVar[list[dict]] = [
        {"id": "deepseek-chat", "type": "chat", "roles": []},
        {"id": "deepseek-reasoner", "type": "chat", "roles": []},
    ]

    def test_models_add(self, cli_runner, fake_http_client):
        """--add 新模型 → GET 现有后 PATCH 全量 models（含新模型）."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = _make_provider(
            models=list(self._EXISTING_MODELS)
        )
        fake_http_client.patch.return_value = _make_provider(
            models=[
                *self._EXISTING_MODELS,
                {"id": "deepseek-v3", "type": "chat", "roles": []},
            ]
        )
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "models",
                "--id",
                "1",
                "--add",
                '{"id": "deepseek-v3", "type": "chat", "roles": []}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        call = fake_http_client.patch.await_args
        assert call.args[0] == "/provider-configs/1"
        models = call.kwargs["json"]["models"]
        assert {"id": "deepseek-v3", "type": "chat", "roles": []} in models
        assert len(models) == 3

    def test_models_remove(self, cli_runner, fake_http_client):
        """--remove 模型 id → PATCH 全量 models（不含被删）."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.return_value = _make_provider(
            models=list(self._EXISTING_MODELS)
        )
        fake_http_client.patch.return_value = _make_provider(
            models=[self._EXISTING_MODELS[0]]
        )
        result = cli_runner.invoke(
            app,
            ["provider", "models", "--id", "1", "--remove", "deepseek-reasoner"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = fake_http_client.patch.await_args
        models = call.kwargs["json"]["models"]
        assert all(m["id"] != "deepseek-reasoner" for m in models)
        assert len(models) == 1

    def test_models_set_json(self, cli_runner, fake_http_client):
        """--set-json 全量替换 → 直接 PATCH（不先 GET）."""
        from inkflow.cli.commands.llm import app

        new_models = [{"id": "gpt-4o", "type": "chat", "roles": []}]
        fake_http_client.patch.return_value = _make_provider(models=new_models)
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "models",
                "--id",
                "1",
                "--set-json",
                json.dumps(new_models),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        call = fake_http_client.patch.await_args
        assert call.kwargs["json"]["models"] == new_models
        fake_http_client.get.assert_not_awaited()

    def test_models_mutually_exclusive(self, cli_runner, fake_http_client):
        """--add 与 --set-json 互斥 → 用法错误退出码 2."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            [
                "provider",
                "models",
                "--id",
                "1",
                "--add",
                '{"id": "x", "type": "chat", "roles": []}',
                "--set-json",
                "[]",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()
        fake_http_client.patch.assert_not_awaited()

    def test_models_get_not_found(self, cli_runner, fake_http_client):
        """GET 现有失败（Provider 不存在）→ NOT_FOUND."""
        from inkflow.cli.commands.llm import app

        fake_http_client.get.side_effect = _http_error(404, "Provider 不存在")
        result = cli_runner.invoke(
            app,
            [
                "provider",
                "models",
                "--id",
                "999",
                "--add",
                '{"id": "x", "type": "chat"}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "NOT_FOUND"
        fake_http_client.patch.assert_not_awaited()

    def test_models_set_json_invalid(self, cli_runner, fake_http_client):
        """--set-json 非法 JSON → VALIDATION_ERROR + 不调用 PATCH."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "models", "--id", "1", "--set-json", "{bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.patch.assert_not_awaited()

    def test_models_add_invalid_json(self, cli_runner, fake_http_client):
        """--add 非法 JSON → VALIDATION_ERROR + 不调用 PATCH/GET."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["provider", "models", "--id", "1", "--add", "{bad"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.get.assert_not_awaited()
        fake_http_client.patch.assert_not_awaited()


class TestLlmTest:
    def test_test_ok(self, cli_runner, fake_http_client):
        """连通成功 → POST /settings/llm/test + {ok: true} 信封."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = {"ok": True, "message": "连接成功"}
        result = cli_runner.invoke(
            app,
            [
                "test",
                "--provider",
                "deepseek",
                "--api-key",
                "sk-test",
                "--model",
                "deepseek-chat",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["ok"] is True
        call = fake_http_client.post.await_args
        assert call.args[0] == "/settings/llm/test"
        body = call.kwargs["json"]
        assert body["provider"] == "deepseek"
        assert body["api_key"] == "sk-test"

    def test_test_fail_ok_false(self, cli_runner, fake_http_client):
        """连通失败 → 200 + {ok: false}（业务语义成功，退出码 0）."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = {
            "ok": False,
            "message": "LLM 连接失败，请检查 Provider / 模型 / API Key 配置",
        }
        result = cli_runner.invoke(
            app,
            ["test", "--provider", "deepseek", "--api-key", "sk-test"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "失败" in result.output or "❌" in result.output

    def test_test_http_error(self, cli_runner, fake_http_client):
        """HTTP 5xx → INTERNAL_ERROR 信封 + 退出码 1."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.side_effect = _http_error(500, "内部错误")
        result = cli_runner.invoke(
            app,
            ["test", "--provider", "deepseek", "--api-key", "sk-test"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_test_with_base_url(self, cli_runner, fake_http_client):
        """--base-url 透传进请求体."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = {"ok": True, "message": "连接成功"}
        result = cli_runner.invoke(
            app,
            [
                "test",
                "--provider",
                "deepseek",
                "--api-key",
                "sk-test",
                "--base-url",
                "https://probe.example/v1",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body = fake_http_client.post.await_args.kwargs["json"]
        assert body["base_url"] == "https://probe.example/v1"

    def test_test_ok_human(self, cli_runner, fake_http_client):
        """人类模式连通成功 → ✅ 输出."""
        from inkflow.cli.commands.llm import app

        fake_http_client.post.return_value = {"ok": True, "message": "连接成功"}
        result = cli_runner.invoke(
            app,
            ["test", "--provider", "deepseek", "--api-key", "sk-test"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "连接成功" in result.output


class TestKeyRemove:
    @pytest.fixture
    def mock_key_manager(self):
        with patch("inkflow.cli.commands.llm.APIKeyManager", autospec=True) as mock_cls:
            mock_km = MagicMock()
            mock_cls.return_value = mock_km
            yield mock_km

    def test_key_remove_json(self, cli_runner, mock_key_manager):
        """llm key remove → APIKeyManager.delete + 信封."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["key", "remove", "--provider", "deepseek"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["provider"] == "deepseek"
        assert data["data"]["status"] == "removed"
        mock_key_manager.delete.assert_called_once_with("deepseek")

    def test_key_remove_human(self, cli_runner, mock_key_manager):
        """人类模式删除成功提示."""
        from inkflow.cli.commands.llm import app

        result = cli_runner.invoke(
            app,
            ["key", "remove", "--provider", "deepseek"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "deepseek" in result.output

    def test_key_remove_not_found(self, cli_runner, mock_key_manager):
        """无 key 文件 → FileNotFoundError → NOT_FOUND 信封 + 退出码 1."""
        from inkflow.cli.commands.llm import app

        mock_key_manager.delete.side_effect = FileNotFoundError(
            "No key file found for provider: deepseek"
        )
        result = cli_runner.invoke(
            app,
            ["key", "remove", "--provider", "deepseek"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
