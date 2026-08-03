"""F16 风格检测 REST API — POST /api/v1/projects/{project_id}/style/analyze。

端点风格沿用 F14/F15（spec §3.1）：风格分析是项目级只读计算，嵌套项目路径；
用 POST 而非 GET——有请求体（text/chapter_ids 互斥输入，spec §2.8），镜像
F9 /characters/extract 与 F14 /extract 的 POST 先例；幂等性由确定性计算保证
（同输入同输出，spec §6.4）。

请求体 StyleAnalyzeRequest（API 层 DTO，spec §2.8）:
- text: str | None（≤ 50000 字符，与 chapter_ids 互斥）
- chapter_ids: list[uuid.UUID] | None（1-100 个，与 text 互斥）
- llm_analysis: bool | None（None = 跟随项目配置 extra["style_llm_analysis"]）

端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级 `_get_svc(db)`
获取 StyleService —— 单元测试通过 `@patch("inkflow.api.routers.style.get_style_service")`
来 mock 服务层（同 F9-F15 模式）。

错误映射（spec §3.3 异常映射表）:
- 无效 UUID（_parse_id）/ 项目不存在（ProjectNotFoundError）→ 404「项目不存在」
- StyleValidationError（业务校验失败）→ 422，消息即 detail
- StyleLLMUnavailableError / StyleLLMAnalysisError / LLMRequestError
  （LLM 深度分析错误，仅 llm_analysis=true 可达）→ 500，消息即 detail
- 其余异常（DB 读取失败等）→ 500「内部错误: ...」（全局处理器语义，ADR-012/016）

依据: specs/f16-style-service/spec.md §3/§7/§9。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_style_service
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.style_errors import (
    StyleLLMAnalysisError,
    StyleLLMUnavailableError,
    StyleValidationError,
)
from inkflow.domain.services.style_service import StyleService

router = APIRouter(prefix="/api/v1", tags=["风格检测"])

_MAX_TEXT_CHARS = 50000
"""手动文本分析上限（spec §2.8/§7: text ≤ 50000 字符）。"""

_MAX_CHAPTER_IDS = 100
"""章节模式数量上限（spec §2.8: chapter_ids ≤ 100 个）。"""


class StyleAnalyzeRequest(BaseModel):
    """风格分析请求体（spec §2.8）— text 与 chapter_ids 互斥，至少其一。

    llm_analysis 三级覆盖（Q1=C）: None = 跟随项目配置
    extra["style_llm_analysis"]（默认 false）；显式 true/false 覆盖项目配置。
    """

    text: str | None = Field(default=None, max_length=_MAX_TEXT_CHARS)
    chapter_ids: list[uuid.UUID] | None = Field(
        default=None, min_length=1, max_length=_MAX_CHAPTER_IDS
    )
    llm_analysis: bool | None = None

    @model_validator(mode="after")
    def _check_source_exclusive(self) -> StyleAnalyzeRequest:
        """输入源互斥校验（spec §2.8/§7）: 同给 / 均缺 → 422。"""
        if self.text is not None and self.chapter_ids is not None:
            raise ValueError("text 与 chapter_ids 不能同时使用")
        if self.text is None and self.chapter_ids is None:
            raise ValueError("必须提供 text 或 chapter_ids")
        return self


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


def _get_svc(db: AsyncSession) -> StyleService:
    """获取 StyleService 实例（方便 mock）。"""
    return get_style_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3 异常映射表）。

    404: ProjectNotFoundError（项目不存在，消息即 detail）。
    422: StyleValidationError（业务校验失败，消息即 detail）。
    500: StyleLLMUnavailableError / StyleLLMAnalysisError / LLMRequestError
        （LLM 深度分析错误，消息即 detail——镜像 F14 RAGUnavailableError
        透传先例，spec §3.3）；其余异常（DB 读取失败等）→「内部错误: ...」。
    """
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except StyleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (StyleLLMUnavailableError, StyleLLMAnalysisError, LLMRequestError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内部错误: {e}") from e


@router.post("/projects/{project_id}/style/analyze")
async def analyze_style(
    request: StyleAnalyzeRequest,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """风格分析（只读幂等，无副作用，spec §3.1/§5）。

    返回完整 StyleReport（fingerprint/ai_trace/lexical 三大板块 + 可选
    llm_assessment 板块），model_dump(mode="json") 信封序列化（spec §3.2）。
    """
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    report = await _run_service(
        svc.analyze(
            project_id=pid,
            text=request.text,
            chapter_ids=request.chapter_ids,
            llm_analysis=request.llm_analysis,
        )
    )
    return report.model_dump(mode="json")
