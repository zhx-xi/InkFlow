"""#977 instance.env 全键 → GET /api/v1/config 端到端契约测试（RED-2 轨，顶层 tests/api/）。

契约节 #977 §0-②/§3/§4 RED-2c：instance.env 写入 INKFLOW_LLM_DEFAULT_MODEL →
InkFlowConfig().llm_default_model 读入（settings_customise_sources 并入 instance.env 源）→
api.routers.config 消费同源字段（config.py:24 config.llm_default_model）→ GET /api/v1/config
default_model 非空 == 值。

【RED】config.py:106-114 InkFlowConfig 无 settings_customise_sources 覆写 → instance.env
键不入 pydantic 源 → llm_default_model 仍为 ""，两断言均 FAIL；GREEN 后（§3 类方法补入
源）复绿。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.config as config_router
from inkflow.api.app import app
from inkflow.core.config import InkFlowConfig


def _patch_anchor(monkeypatch, anchor: Path) -> None:
    """把 config 模块的 get_instance_env_path 替换为固定锚点（测试隔离用）。

    镜像 backend/tests/unit/core/test_config_instance_env.py:50 同款手法：
    RED 阶段属性存在（config.py:16）→ raising=False 容忍；GREEN 阶段覆盖真实函数，
    load_instance_env 命中锚点；防本机真实 %APPDATA%/InkFlow/instance.env 注入。
    """
    module = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(module, "get_instance_env_path", lambda: anchor, raising=False)


@pytest.mark.asyncio
@pytest.mark.api
async def test_get_config_reflects_instance_env_default_model(monkeypatch, tmp_path):
    """【R】instance.env INKFLOW_LLM_DEFAULT_MODEL → GET /api/v1/config default_model。

    契约节 #977 §3 不变式：instance.env 新键 INKFLOW_LLM_DEFAULT_MODEL=
    deepseek/deepseek-v4-flash → 重建 InkFlowConfig().llm_default_model == 该值；
    monkeypatch api.routers.config 模块 config 为该实例 → GET /api/v1/config
    default_model 非空 == 值（config.py:24 同源字段）。

    RED：settings_customise_sources 未实现 → instance.env 键不入源 → llm_default_model
    仍为 ""，重建断言 + HTTP 断言均 FAIL。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_LLM_DEFAULT_MODEL=deepseek/deepseek-v4-flash\n", encoding="utf-8")
    # 隔离：delenv 同名（conftest.py setdefault 注入，防进程 env 误判）+ delenv token
    # 免鉴权中间件阻塞；instance.env 仅放 model 键（不触发 debug/config.json 降级分支）。
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)

    rebuilt = InkFlowConfig()

    assert rebuilt.llm_default_model == "deepseek/deepseek-v4-flash"

    monkeypatch.setattr(config_router, "config", rebuilt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["default_model"]
    assert body["default_model"] == "deepseek/deepseek-v4-flash"
