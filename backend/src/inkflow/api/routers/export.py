"""F21 导出服务 REST API — GET /api/v1/projects/{project_id}/export。

端点风格沿用 F15（spec §3.1）：导出是项目级只读计算，嵌套项目路径，
用 GET——镜像 F15 `GET /api/v1/projects/{project_id}/audit` 先例
（幂等只读计算无副作用，GET 语义正确且可缓存）。v1.1 仅接受
`format=txt`（spec §3.1/§12 D9），TXT 序列化后以附件字节流返回。

端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 ExportService——单元测试通过
`@patch("inkflow.api.routers.export._get_svc")` 来 mock 服务层
（同 F9-F15 模式）。

错误映射（spec §3.3 异常映射表）:
- 无效 UUID / 项目不存在（ProjectNotFoundError）→ 404「项目不存在」
- 任一档案仓储读取失败 / 序列化失败 → 500「内部错误: ...」透传
- format 非 txt → FastAPI 自动 422（Pydantic Literal 校验短路，
  service 零调用）

依据: specs/f21-export/spec.md §3/§7/§9。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_export_service
from inkflow.domain.models.output import ExportFormat
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services import _txt_exporter
from inkflow.domain.services._export_filename import suggest_filename
from inkflow.domain.services.output_service import ExportService
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1", tags=["导出"])


def _parse_id(project_id: str) -> uuid.UUID:
    """安全解析项目 ID 字符串，支持 UUID 格式和整数格式（同 F9-F15）。

    无效 UUID → 404「项目不存在」（spec §3.3，统一解析失败处理，
    不进入服务层）。
    """
    try:
        return uuid.UUID(project_id)
    except ValueError:
        try:
            return uuid.UUID(int=int(project_id))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail="项目不存在") from err


def _get_svc(db: AsyncSession) -> ExportService:
    """获取 ExportService 实例（方便 mock）。"""
    return get_export_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）。

    404: ProjectNotFoundError（项目不存在，消息即 detail）。
    500: 其余异常透传（任一档案仓储读取失败 / 序列化失败），
    detail 格式「内部错误: ...」（spec §3.3）。
    """
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内部错误: {e}") from e


@router.get("/projects/{project_id}/export")
@instrument(caller_type="api")
async def export_project(
    project_id: str,
    format: Literal["txt"] = "txt",
    include_settings: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """导出项目 TXT（只读幂等，spec §3.1/§5）。

    服务层聚合 BookDocument（§5.1）→ TXT 序列化器（§5.3）→
    UTF-8 字节流附件响应（§3.2）；文件名经 URL 编码防中文/空格
    破坏头（§7 E6）。
    """
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    book = await _run_service(svc.export(pid, include_settings=include_settings))
    txt = _txt_exporter.to_txt(book)
    filename = suggest_filename(book.meta.title, ExportFormat.TXT)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    return Response(
        content=txt.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers=headers,
    )
