"""F15 一致性审计 REST API — GET /api/v1/projects/{project_id}/audit。

端点风格沿用 F12（spec §3.1）：审计是项目级只读计算，嵌套项目路径，
用 GET 而非 POST——镜像 F12 `GET /api/v1/projects/{project_id}/timeline/check`
先例（幂等只读计算无副作用，GET 语义正确且可缓存）。无请求体、无查询
参数（YAGNI，spec §3.1 注）——错误面只有 404 与 500（spec §3.3）。

端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`_get_svc(db)` 获取 AuditService —— 单元测试通过
`@patch("inkflow.api.routers.audit.get_audit_service")` 来 mock 服务层
（同 F9-F14 模式）。

错误映射（spec §3.3 异常映射表）:
- 无效 UUID / 项目不存在（ProjectNotFoundError）→ 404「项目不存在」
- 任一档案仓储读取失败 / 委托 F12 check_consistency 失败 → 500
  「内部错误: ...」透传
- 无 422 业务校验错误（F15 唯一输入是路径 project_id，无请求体/查询
  参数，错误面只有 404 与 500）

依据: specs/f15-consistency-audit/spec.md §3/§7。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_audit_service, get_db
from inkflow.domain.ports.audit_errors import ProjectNotFoundError
from inkflow.domain.services.audit_service import AuditService
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1", tags=["审计"])


def _parse_id(project_id: str) -> uuid.UUID:
    """安全解析项目 ID 字符串，支持 UUID 格式和整数格式（同 F9-F14）。

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


def _get_svc(db: AsyncSession) -> AuditService:
    """获取 AuditService 实例（方便 mock）。"""
    return get_audit_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）。

    404: ProjectNotFoundError（项目不存在，消息即 detail）。
    500: 其余异常透传（任一档案仓储读取失败 / 委托 F12 失败），
    detail 格式「内部错误: ...」（spec §3.3）。
    """
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内部错误: {e}") from e


@router.get("/projects/{project_id}/audit")
@instrument(caller_type="api")
async def audit_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """4 维度一致性审计（只读幂等，无副作用，spec §3.1/§5）。

    返回完整 AuditReport（summary + findings + timeline_check 嵌套 F12
    原始报告），model_dump(mode="json") 信封序列化（spec §3.2）。
    """
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    report = await _run_service(svc.run_audit(pid))
    return report.model_dump(mode="json")
