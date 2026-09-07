"""#987 config.json 启动读回 → GET /api/v1/config 端到端契约测试（顶层 tests/api/）。

契约节 #987 回归第 4 条：PATCH /api/v1/config 落盘 config.json → 模拟重启
（重新构造 InkFlowConfig()，monkeypatch 路由模块 config 为新实例）→
GET /api/v1/config default_model 仍非空 == 落盘值（CLI show ↔ HTTP 同源一致）。

镜像 #977 tests/api/test_config_instance_env_api.py 手法（锚点隔离 + delenv
token 免鉴权中间件阻塞 + 重建实例注入路由模块）。

【RED】config.json 非启动源 → 重建实例 llm_default_model 回 ""，两断言均 FAIL；
GREEN 后（ConfigJsonSettingsSource 并入）复绿。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.config as config_router
from inkflow.api.app import app
from inkflow.core.config import InkFlowConfig


def _patch_anchor(monkeypatch, anchor: Path) -> None:
    """把 config 模块的 get_instance_env_path 替换为固定锚点（测试隔离用）。"""
    module = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(module, "get_instance_env_path", lambda: anchor, raising=False)


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_config_survives_restart_with_config_json(monkeypatch, tmp_path):
    """【R】config.json 含 llm_default_model → 重启构造 InkFlowConfig() 非空 →
    GET /api/v1/config default_model == 落盘值。

    等价 issue 复现步骤 1-2 的测试态：不真发 PATCH（单例副作用跨用例），直接落盘
    config.json（save_config_json 的产物形态，键=llm_default_model，api/routers/
    config.py:54 同源）+ 重建实例注入路由模块 → HTTP 断言。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("", encoding="utf-8")
    # 隔离：delenv 同名（conftest.py:17 setdefault 注入）+ token 免鉴权 + DEBUG
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "config.json").write_text(
        json.dumps({"llm_default_model": "deepseek/deepseek-v4-flash"}),
        encoding="utf-8",
    )

    rebuilt = InkFlowConfig(data_dir=data_dir)

    assert rebuilt.llm_default_model == "deepseek/deepseek-v4-flash"

    monkeypatch.setattr(config_router, "config", rebuilt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["default_model"]
    assert body["default_model"] == "deepseek/deepseek-v4-flash"
