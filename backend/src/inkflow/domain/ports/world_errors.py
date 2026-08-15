"""世界观管理领域异常.

F10 专属异常类型，继承自 Exception。
依据: specs/f10-world-service/spec.md §5/§8。

异常映射约定（spec §3.5 异常映射表）:
- WorldServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- WorldNotFoundError / ProjectNotFoundError = 资源不存在，API 层映射为 404
- WorldExtractionError = LLM 输出解析失败，API 层映射为 500
"""

from __future__ import annotations


class WorldExtractionError(Exception):
    """世界观提取失败 — LLM 输出无法解析为合法条目 JSON.

    修复重试耗尽后抛出，由调用方（API/CLI）映射为 LLM_ERROR 错误信封。

    Attributes:
        raw_output: LLM 原始输出片段（诊断用，可能被截断）.
        detail: 失败原因描述.
    """

    def __init__(self, raw_output: str = "", detail: str = "") -> None:
        self.raw_output = raw_output
        self.detail = detail
        msg = "世界观提取失败: LLM 输出无法解析为合法 JSON"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class WorldServiceError(Exception):
    """世界观服务业务校验失败基类 — API 层映射为 422.

    子类消息即 422 响应 detail（spec §3.5 中文文案）。
    """


class WorldNotFoundError(Exception):
    """世界观条目不存在 — API 层映射为 404「世界观条目不存在」.

    用于 create_relation 等返回非 Optional 的方法（路径条目缺失）；
    其余 CRUD 方法以返回 None 表达不存在（router 层统一转 404）。
    """

    def __init__(self, message: str = "世界观条目不存在") -> None:
        super().__init__(message)


class ProjectNotFoundError(Exception):
    """项目不存在 — extract 入口校验失败，API 层映射为 404「项目不存在」."""

    def __init__(self, message: str = "项目不存在") -> None:
        super().__init__(message)


class WorldNameConflictError(WorldServiceError):
    """同名世界观条目已存在（条目名在项目内必须唯一）— 422."""

    def __init__(self, message: str = "同名世界观条目已存在（条目名在项目内必须唯一）") -> None:
        super().__init__(message)


class WorldParentNotFoundError(WorldServiceError):
    """父地点不存在或不在同一项目 — 422.

    用于 create/update 挂接时父节点校验失败（spec §7 边界 1/2/3）。
    """

    def __init__(self, message: str = "父地点不存在或不在同一项目") -> None:
        super().__init__(message)


class WorldCycleError(WorldServiceError):
    """循环引用：parent 是自身或其子孙 — 422.

    循环防护（spec §5.2）检测到挂接形成环时抛出（spec §7 边界 4/5）。
    """

    def __init__(self, message: str = "不能将地点挂接到自身或其子孙下") -> None:
        super().__init__(message)


class WorldChildrenActionRequiredError(WorldServiceError):
    """有子地点时必须显式选择级联删除或 reparent — 422（spec §5.5）."""

    def __init__(
        self,
        message: str = (
            "该地点存在子地点，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<id>（子地点改挂新父）"
        ),
    ) -> None:
        super().__init__(message)


class WorldReparentTargetError(WorldServiceError):
    """reparent 目标非法（不存在/跨项目/自身子树）— 422（spec §7 边界 11）."""

    def __init__(self, message: str = "reparent 目标地点不存在/不在同一项目/是自身子树") -> None:
        super().__init__(message)


class CopySourceNotFoundError(Exception):
    """源项目不存在 — 复制入口校验失败，API 层映射为 404「源项目不存在」."""

    def __init__(self, message: str = "源项目不存在") -> None:
        super().__init__(message)


class CopyRootNotFoundError(Exception):
    """复制起点条目不存在或不在源项目 — API 层映射为 404「复制起点条目不存在或不在源项目」."""

    def __init__(self, message: str = "复制起点条目不存在或不在源项目") -> None:
        super().__init__(message)


class WorldCategoryNameConflictError(WorldServiceError):
    """同名世界观分类已存在 — 422."""

    def __init__(self, message: str = "同名世界观分类已存在") -> None:
        super().__init__(message)


class WorldCategoryNotFoundError(Exception):
    """世界观分类不存在 — 404."""

    def __init__(self, message: str = "世界观分类不存在") -> None:
        super().__init__(message)
