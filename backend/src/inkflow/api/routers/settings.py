"""设置 REST API — 基础设施工具端点（API Key 存储 + LLM 连通探测）。

对应 F19 GUI 渲染层（spec §4.4/§4.6，Q3 拍板）的 2 个工具端点：
- POST /api/v1/settings/llm-keys — APIKeyManager AES-256-GCM 加密存储 API Key
- POST /api/v1/settings/llm/test — LLMClient 最小连通探测

安全红线：响应体禁止回显明文 api_key；探测端点的 api_key 仅用于本次
请求（内存构造客户端），不落盘。
"""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from inkflow.core.config import config
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.infrastructure.llm.key_manager import APIKeyManager
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


def _validate_not_blank(v: str, field_name: str) -> str:
    """strip 后非空校验（与 F3 WritingRequest outline 空白拒绝行为对齐）。"""
    stripped = v.strip()
    if not stripped:
        raise ValueError(f"{field_name} 不能为空")
    return stripped


_PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class LLMKeyStoreRequest(BaseModel):
    """POST /llm-keys 请求体 — provider/api_key 必填非空（多余字段忽略）。"""

    provider: str
    api_key: str

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        stripped = _validate_not_blank(v, "provider")
        if not _PROVIDER_RE.match(stripped):
            raise ValueError("provider 仅允许小写字母/数字/下划线/连字符，1-32 字符")
        return stripped

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        return _validate_not_blank(v, "api_key")


class LLMTestRequest(BaseModel):
    """POST /llm/test 请求体 — provider/model/api_key 必填非空。"""

    provider: str
    model: str
    api_key: str

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        stripped = _validate_not_blank(v, "provider")
        if not _PROVIDER_RE.match(stripped):
            raise ValueError("provider 仅允许小写字母/数字/下划线/连字符，1-32 字符")
        return stripped

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        return _validate_not_blank(v, "model")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        return _validate_not_blank(v, "api_key")


def _get_key_manager() -> APIKeyManager:
    """构造 APIKeyManager（镜像 cli/commands/llm.py 工厂模式）。"""
    return APIKeyManager(
        secret_key=config.secret_key,
        storage_dir=config.data_dir / "keys",
    )


def _get_llm_client(provider: str, model: str, api_key: str) -> LLMClientProtocol:
    """按请求参数构造 LLM 客户端（连通探测用，api_key 仅内存本次使用）。"""
    model_ref = model if "/" in model else f"{provider}/{model}"
    return LangChainLLMClient(default_model=model_ref, api_key=api_key)


@router.post("/llm-keys", status_code=201)
async def store_llm_key(data: LLMKeyStoreRequest) -> dict:
    """加密存储 Provider API Key — 201 + {provider, status: saved}（镜像 CLI set-key JSON 输出）。

    存储异常 → 500 通用 detail（ADR-012 风格，不泄漏内部细节）。
    """
    km = _get_key_manager()
    try:
        km.store(data.provider, data.api_key)
    except Exception as exc:
        logger.exception("API Key 存储失败: provider=%s", data.provider)
        raise HTTPException(status_code=500, detail="API Key 存储失败，请稍后重试") from exc
    return {"provider": data.provider, "status": "saved"}


@router.post("/llm/test")
async def test_llm_connection(data: LLMTestRequest) -> dict:
    """LLM 连通探测 — 业务语义成功/失败 → 200 + {ok: ...}（spec §4.2.3 testStatus 消费语义）。

    失败（LLMRequestError/网络等）→ 200 + ok:false 通用文案，内部异常细节不泄漏。
    """
    try:
        client = _get_llm_client(data.provider, data.model, data.api_key)
        probe = client.chat([ChatMessage(role="user", content="ping")])
        # LLMClientProtocol.chat 为 async 协程；防御探测桩返回非 awaitable 的边界
        if asyncio.iscoroutine(probe):
            await probe
    except Exception:
        logger.warning("LLM 连通探测失败: provider=%s model=%s", data.provider, data.model)
        return {
            "ok": False,
            "message": "LLM 连接失败，请检查 Provider / 模型 / API Key 配置",
        }
    return {
        "ok": True,
        "provider": data.provider,
        "model": data.model,
        "message": "连接成功",
    }
