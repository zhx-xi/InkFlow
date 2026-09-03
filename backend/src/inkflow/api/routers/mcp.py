"""MCP 自发现 REST API（Issue #563）— GET /api/v1/mcp/info。

只读、无副作用、无鉴权豁免（TokenAuthMiddleware 统一处理）；不做 MCP 集成本体。
"""

from __future__ import annotations

from fastapi import APIRouter

from inkflow.logging import instrument
from inkflow.mcp.info import build_mcp_info

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP"])


@router.get("/info")
@instrument(caller_type="api")
async def get_mcp_info() -> dict:
    """MCP 自发现信息（spec f50 §3.2）— client_path + version + config_template。"""
    return build_mcp_info()
