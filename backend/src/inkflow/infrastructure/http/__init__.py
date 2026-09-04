"""HTTP 传输层 —— Issue #169 CLI 恒经 HTTP 路由改造（ADR-030 ② D1=A）。

对外导出四符号：InkFlowHTTPClient / HttpApiError / map_http_error / LLM_TASK_TIMEOUT。
"""

from inkflow.infrastructure.http.client import HttpApiError, InkFlowHTTPClient
from inkflow.infrastructure.http.errors import map_http_error

# #926：LLM 长任务 per-request 超时共享常量，对齐 #274 write._AGENTIC_TIMEOUT 的 300s。
LLM_TASK_TIMEOUT: float = 300.0

__all__ = ["LLM_TASK_TIMEOUT", "HttpApiError", "InkFlowHTTPClient", "map_http_error"]
