"""全局配置 REST API（Issue #526）— GUI 补 CLI config show/set 的 HTTP 面。

- GET  /api/v1/config —— 镜像 CLI config show 的 7 键
- PATCH /api/v1/config —— body {llm_default_model} → save_config_json 落盘
  + 内存 config 单例同步（立即生效，deps 装配读取点随后次请求生效）
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from inkflow.core.config import config, save_config_json

router = APIRouter(prefix="/api/v1/config", tags=["Config"])


@router.get("")
async def get_config() -> dict:
    """读取全局配置（#526）— CLI config show 同款键。"""
    return {
        "default_model": config.llm_default_model,
        "default_temperature": config.llm_temperature,
        "context_max_ratio": config.context_max_ratio,
        "context_default_window": config.context_default_window,
        "server_host": config.server_host,
        "server_port": config.server_port,
        "data_dir": str(config.data_dir),
    }


class ConfigUpdate(BaseModel):
    """PATCH /api/v1/config 请求体 — 仅 llm_default_model（白名单单键，extra=forbid）。"""

    llm_default_model: str
    model_config = {"extra": "forbid"}

    @field_validator("llm_default_model")
    @classmethod
    def validate_llm_default_model(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("llm_default_model 不能为空")
        return stripped


@router.patch("")
async def patch_config(data: ConfigUpdate) -> dict:
    """保存全局默认模型（#526）— config.json 持久化 + 内存单例立即生效。"""
    config.llm_default_model = data.llm_default_model
    save_config_json(config.data_dir, {"llm_default_model": data.llm_default_model})
    return await get_config()
