"""F14 统一提取服务领域异常.

F14 专属异常类型，继承自 Exception。
依据: specs/f14-extraction-service/spec.md §7 边界情况与错误处理 + §8 文件清单。

异常映射约定（spec §7）:
- ExtractionServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- RAGUnavailableError / VectorStoreError / ExtractionRunError = 基础设施
  错误，API 层映射为 500

与 F9-F13 的差异: F14 是横切收敛型门面，错误类覆盖「类型校验 + 章节校验 +
RAG 基础设施」三类新语义；通用名错误类（ProjectNotFoundError 等）不在本
模块重复定义/导出（F9 character_errors 已有同名导出，避免遮蔽既有 router）。
"""

from __future__ import annotations


class ExtractionServiceError(Exception):
    """提取服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §7 中文文案）。
    """


class ExtractionValidationError(ExtractionServiceError):
    """提取请求校验失败（类型相关参数约束，§6.4）— 422.

    类型不匹配的字段一律 422 而非静默忽略（显式错误优先，同 F13 event_id
    校验风格）。
    """

    def __init__(self, message: str = "提取请求参数不合法") -> None:
        super().__init__(message)


class UnsupportedExtractionTypeError(ExtractionServiceError):
    """不支持的提取类型 — 422.

    用于 type 为合法字符串但不在 ExtractionType 6 种枚举内（如 F16 落地前
    的未知类型扩展值）。
    """

    def __init__(self, message: str = "不支持的提取类型") -> None:
        super().__init__(message)


class StyleNotImplementedError(ExtractionServiceError):
    """STYLE 类型未实现（F16 风格检测未落地，注册占位）— 422「风格提取尚未实现」.

    接口契约（枚举/API/CLI）全量支持，调用返回 422（§6.1；Q1 ✅ 已确认选项 A）；
    F16 落地后仅需注册 handler。
    """

    def __init__(self, message: str = "风格提取尚未实现（依赖 F16 风格检测）") -> None:
        super().__init__(message)


class ChapterNotFoundError(ExtractionServiceError):
    """章节不存在（含已软删章节，F2 get 不含软删）— 422「章节不存在」."""

    def __init__(self, message: str = "章节不存在") -> None:
        super().__init__(message)


class ChapterNotInProjectError(ExtractionServiceError):
    """chapter_ids 指向其他项目的章节 — 422「章节不属于该项目」."""

    def __init__(self, message: str = "章节不属于该项目") -> None:
        super().__init__(message)


class RAGUnavailableError(Exception):
    """RAG 向量存储不可用（未装配 / 初始化失败）— 500.

    门面 index=true 但 vector_store 未注入时抛出（§5.6/§6.3）。
    """

    def __init__(self, message: str = "向量检索服务不可用") -> None:
        super().__init__(message)


class VectorStoreError(Exception):
    """向量存储操作失败（index/retrieve/delete 底层异常）— 500."""

    def __init__(self, message: str = "向量存储操作失败") -> None:
        super().__init__(message)


class ExtractionRunError(Exception):
    """增量追踪记录（extraction_runs）读写失败 — 500.

    门面增量判定/落库依赖 run_repo，仓储异常统一封装为该错误（§5.2）。
    """

    def __init__(self, message: str = "提取记录读写失败") -> None:
        super().__init__(message)
