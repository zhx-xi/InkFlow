"""HTTP 错误码映射 —— Issue #169 CLI 恒经 HTTP 路由改造（ADR-030 ②，spec §5.3）。"""

from __future__ import annotations


def map_http_error(status_code: int, detail: str, header_code: str | None) -> tuple[str, str]:
    """将 HTTP 状态码映射为 (错误码, 展示消息)，供命令层捕获 HttpApiError 后调用。

    spec §5.3 映射表：
    - header_code == TIMEOUT（传输层超时，#926）→ ("TIMEOUT", detail or "请求超时")
    - 404 → ("NOT_FOUND", detail)
    - 422 → ("VALIDATION_ERROR", detail)
    - 401 → ("CONFIG_ERROR", detail)
    - 403 → ("INTERNAL_ERROR", detail)
    - 500 + X-InkFlow-Error-Code: LLM_ERROR → ("LLM_ERROR", detail)
    - 其余状态码（含 500 无 header_code）→ ("INTERNAL_ERROR", detail)
    展示消息 = detail 原样透传；detail 为空时使用兜底诊断文案（#634，
    避免 MCP/CLI 暴露 "INTERNAL_ERROR: " 这类空消息）。
    """
    if header_code == "TIMEOUT":
        return "TIMEOUT", detail or "请求超时"
    if status_code == 404:
        return "NOT_FOUND", detail or "资源不存在"
    if status_code == 422:
        return "VALIDATION_ERROR", detail or "参数校验失败"
    if status_code == 401:
        return "CONFIG_ERROR", detail or "鉴权失败"
    if status_code == 403:
        return "INTERNAL_ERROR", detail or "无权限"
    if status_code == 500 and header_code == "LLM_ERROR":
        return "LLM_ERROR", detail or "内部错误（无详情）"
    return "INTERNAL_ERROR", detail or "内部错误（无详情）"
