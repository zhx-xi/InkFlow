"""F16 风格检测服务领域异常.

F16 专属异常类型，继承自 Exception。
依据: specs/f16-style-service/spec.md §3.3 异常映射表 + §7 边界情况与
错误处理 + §8 文件清单。

异常映射约定（spec §3.3/§7）:
- StyleServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- StyleLLMUnavailableError / StyleLLMAnalysisError = LLM 深度分析基础设施
  错误（500 家族），API 层映射为 500——仅 llm_analysis=true 时可达
  （Q1=C：LLM 深度分析默认关闭）

与 F9-F15 的差异: F16 错误类覆盖「输入校验 + LLM 深度分析」两类新语义；
通用名错误类（ProjectNotFoundError 等）不在本模块重复定义/导出
（F9 character_errors 已有同名导出，避免遮蔽既有 router）；章节校验
复用 F14 extraction_errors（ChapterNotFoundError / ChapterNotInProjectError）。
"""

from __future__ import annotations


class StyleServiceError(Exception):
    """风格检测服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.3/§7 中文文案）。
    """


class StyleValidationError(StyleServiceError):
    """风格分析请求校验失败（输入互斥/缺失/空文本/章节超长）— 422.

    服务层校验抛出的具体文案即 422 响应 detail（spec §7 错误表）:
    「text 与 chapter_ids 不能同时使用」/「必须提供 text 或 chapter_ids」/
    「文本不能为空」/「章节内容超过分析上限（50000 字符）」。
    """

    def __init__(self, message: str = "风格检测请求参数不合法") -> None:
        super().__init__(message)


class StyleLLMUnavailableError(Exception):
    """LLM 深度分析器未装配（deps 层可选装配）— 500.

    llm_analysis=true 但分析器未注入时抛出（spec §5.6/§7）——镜像 F14
    RAGUnavailableError 语义：可选能力未装配时显式报错而非静默降级。
    """

    def __init__(self, message: str = "LLM 深度分析不可用") -> None:
        super().__init__(message)


class StyleLLMAnalysisError(Exception):
    """LLM 深度分析解析失败（修复式重试 ≤2 仍失败）— 500.

    LLM 输出无法解析/校验为合法判定 JSON 时抛出（spec §5.6）——同 F14
    TimelineExtractionError 语义，透传给 API/CLI 映射为 500。
    """

    def __init__(self, message: str = "LLM 深度分析解析失败") -> None:
        super().__init__(message)
