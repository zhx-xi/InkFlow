"""大纲管理领域异常.

F11 专属异常类型，继承自 Exception。
依据: specs/f11-outline-service/spec.md §5/§8。

异常映射约定（spec §3.5 异常映射表）:
- OutlineServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- OutlineNotFoundError / PlotPointNotFoundError / StoryArcNotFoundError /
  ProjectNotFoundError = 资源不存在，API 层映射为 404
- OutlineGenerationError = LLM 输出解析失败，API 层映射为 500
"""

from __future__ import annotations


class OutlineGenerationError(Exception):
    """大纲生成失败 — LLM 输出无法解析为合法大纲 JSON.

    修复重试耗尽后抛出，由调用方（API/CLI）映射为 LLM_ERROR 错误信封。

    Attributes:
        raw_output: LLM 原始输出片段（诊断用，可能被截断）.
        detail: 失败原因描述.
    """

    def __init__(self, raw_output: str = "", detail: str = "") -> None:
        self.raw_output = raw_output
        self.detail = detail
        msg = "大纲生成失败: LLM 输出无法解析为合法 JSON"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class OutlineServiceError(Exception):
    """大纲服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.5 中文文案）。
    """


class OutlineNotFoundError(Exception):
    """大纲不存在 — API 层映射为 404「大纲不存在」.

    用于必须返回实体的方法（路径大纲缺失）；
    其余 CRUD 方法以返回 None 表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "大纲不存在") -> None:
        super().__init__(message)


class PlotPointNotFoundError(Exception):
    """情节点不存在 — API 层映射为 404「情节点不存在」."""

    def __init__(self, message: str = "情节点不存在") -> None:
        super().__init__(message)


class StoryArcNotFoundError(Exception):
    """故事弧线不存在 — API 层映射为 404「故事弧线不存在」."""

    def __init__(self, message: str = "故事弧线不存在") -> None:
        super().__init__(message)


class ProjectNotFoundError(Exception):
    """项目不存在 — generate 入口校验失败，API 层映射为 404「项目不存在」."""

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)


class OutlineNameConflictError(OutlineServiceError):
    """同名大纲已存在（大纲名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名大纲已存在（大纲名在项目内必须唯一）") -> None:
        super().__init__(message)


class ArcNameConflictError(OutlineServiceError):
    """同名故事弧线已存在（弧线名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名故事弧线已存在（弧线名在项目内必须唯一）") -> None:
        super().__init__(message)


class ArcNotInProjectError(OutlineServiceError):
    """弧线不存在于该项目（arc_id 归属校验失败）— 422."""

    def __init__(self, message: str = "弧线不存在于该项目") -> None:
        super().__init__(message)


class OutlineLevelError(OutlineServiceError):
    """大纲层级非法（非 overall/volume/chapter）— 422."""

    def __init__(self, message: str = "大纲层级只能为 overall/volume/chapter") -> None:
        super().__init__(message)


class OutlineHierarchyError(OutlineServiceError):
    """大纲层级约束违反（overall 挂父 / volume 非挂 overall / chapter 非挂 volume）— 422."""

    def __init__(self, message: str = "大纲层级约束违反") -> None:
        super().__init__(message)


class OutlineChapterRefError(OutlineServiceError):
    """章关联约束违反（chapter_id 仅 chapter 可设 / 章节不存在或跨项目）— 422."""

    def __init__(self, message: str = "章关联约束违反") -> None:
        super().__init__(message)


class OutlineVolumeRefError(OutlineServiceError):
    """卷关联约束违反（volume_id 仅 volume 可设 / 卷不存在或跨项目 / 卷已关联卷纲）— 422."""

    def __init__(self, message: str = "卷关联约束违反") -> None:
        super().__init__(message)
