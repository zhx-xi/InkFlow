"""F36 地图领域异常 — 继承 Exception（镜像 F10 world_errors 风格）.

异常映射约定（spec §3.3）:
- MapServiceError 子类 = 业务校验失败，API 层映射为 422（消息即 detail）
- MapNotFoundError / MapPinNotFoundError = 资源不存在，API 层映射为 404
- MapAssetError = 文件层错误，API 层映射为 500

ProjectNotFoundError 复用 F10 world_errors（不在本模块重定义——F16 遮蔽教训）。
"""


class MapServiceError(Exception):
    """地图服务业务校验失败基类 — API 层映射为 422."""


class MapNameConflictError(MapServiceError):
    def __init__(self, message: str = "同名地图已存在（项目内）") -> None:
        super().__init__(message)


class MapRootLocationConflictError(MapServiceError):
    def __init__(self, message: str = "该地点已挂有一张地图") -> None:
        super().__init__(message)


class MapRootLocationNotFoundError(MapServiceError):
    def __init__(self, message: str = "父地点不存在或不在同一项目") -> None:
        super().__init__(message)


class MapPinLocationNotFoundError(MapServiceError):
    def __init__(self, message: str = "pin 关联地点不存在或不在同一项目") -> None:
        super().__init__(message)


class MapChildrenActionRequiredError(MapServiceError):
    def __init__(
        self,
        message: str = (
            "该地图存在子地图，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<map_id>（子地图改挂新父）"
        ),
    ) -> None:
        super().__init__(message)


class MapReparentTargetError(MapServiceError):
    def __init__(
        self, message: str = "reparent 目标地图不存在/不在同一项目/是自身子孙地图"
    ) -> None:
        super().__init__(message)


class MapNotFoundError(Exception):
    def __init__(self, message: str = "地图不存在") -> None:
        super().__init__(message)


class MapPinNotFoundError(Exception):
    def __init__(self, message: str = "pin 不存在") -> None:
        super().__init__(message)


class MapAssetError(Exception):
    def __init__(self, message: str = "图片文件读写失败") -> None:
        super().__init__(message)
