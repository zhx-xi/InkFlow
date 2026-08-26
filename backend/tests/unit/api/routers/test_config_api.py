"""#525/#526 RED 契约 — GET/PATCH /api/v1/config 新 router 契约（#526 全局默认模型）。

被测 router: inkflow.api.routers.config（GREEN 批新建，现不存在）:
- ``GET /api/v1/config`` —— 200 + 7 键（镜像 CLI config show）:
  default_model / default_temperature / context_max_ratio /
  context_default_window / server_host / server_port / data_dir
- ``PATCH /api/v1/config`` —— body {llm_default_model} → 200 + default_model
  更新；空串 → 422；未知键 → 422（extra=forbid 语义）；落盘走
  save_config_json（参数含 llm_default_model）+ 内存 config 同步更新

RED 形态: router 未注册 → GET/PATCH 均 404 → 状态码/键断言 FAIL
（纯断言失败）。

⚠️ patch 目标模块尚不存在（规则 1e 逃生门 #266）: 模块级注入同路径 stub
到 sys.modules，使 patch("inkflow.api.routers.config.save_config_json")
可解析 → 测试真正打到端点 → 404 断言 FAIL；GREEN 阶段 app 导入链已注册
真模块，setdefault 不覆盖 → patch 命中端点内全局名，本文件无需改动。

依据: Issue #526 全局默认模型；任务书 s8a red-backend-task.md 文件 3。
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.core.config import config

client = TestClient(app)

# RED 阶段 inkflow.api.routers.config 模块不存在——注入同路径 stub 模块，
# 使 patch 目标可解析（规则 1e 逃生门）→ 端点未注册 → 404 断言 FAIL。
# GREEN 阶段该模块已被 app 导入链注册进 sys.modules，setdefault 不覆盖真模块。
_stub_config_router = ModuleType("inkflow.api.routers.config")
_stub_config_router.save_config_json = MagicMock()
sys.modules.setdefault("inkflow.api.routers.config", _stub_config_router)

CONFIG_KEYS = (
    "default_model",
    "default_temperature",
    "context_max_ratio",
    "context_default_window",
    "server_host",
    "server_port",
    "data_dir",
)


def test_get_config() -> None:
    """契约: GET /api/v1/config → 200 + 7 键全在（镜像 CLI config show）。"""
    resp = client.get("/api/v1/config")
    assert resp.status_code == 200
    body = resp.json()
    for key in CONFIG_KEYS:
        assert key in body


def test_patch_default_model_ok() -> None:
    """契约: PATCH llm_default_model → 200 + default_model 更新 + 落盘 + 内存更新。"""
    save_mock = MagicMock()
    original = config.llm_default_model
    try:
        with patch("inkflow.api.routers.config.save_config_json", save_mock):
            resp = client.patch(
                "/api/v1/config",
                json={"llm_default_model": "deepseek/deepseek-chat"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["default_model"] == "deepseek/deepseek-chat"
        assert config.llm_default_model == "deepseek/deepseek-chat"
        save_mock.assert_called_once()
        values = [*save_mock.call_args.args, *save_mock.call_args.kwargs.values()]
        assert any(
            isinstance(v, dict) and v.get("llm_default_model") == "deepseek/deepseek-chat"
            for v in values
        )
    finally:
        config.llm_default_model = original


def test_patch_blank_model_422() -> None:
    """契约: llm_default_model 空串 → 422。"""
    resp = client.patch("/api/v1/config", json={"llm_default_model": ""})
    assert resp.status_code == 422


def test_patch_unknown_field_422() -> None:
    """契约: body 含未知键（foo）→ 422（extra=forbid 语义）。"""
    resp = client.patch("/api/v1/config", json={"foo": "bar"})
    assert resp.status_code == 422
