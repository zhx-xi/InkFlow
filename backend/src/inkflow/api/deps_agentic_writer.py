"""#1037 agentic writer 装配依赖 — 自 deps.py 迁出（防超 900 行护栏）.

deps.py 以 `from inkflow.api.deps_agentic_writer import get_agentic_writer_service`
re-export，writing.py 与单测仍从 inkflow.api.deps 导入（命名空间不变）。

迁移要点（相对 deps.py 原函数体，行为等价）：
- service getter 与装配类/仓储类经 deps_module（= inkflow.api.deps）命名空间在调用期解析：
  f27 绑定名快照契约——单测 patch 目标是 inkflow.api.deps.<名>
  （test_deps_agentic_model_resolution.py），本模块不得在模块级重新绑定同名符号，
  否则 patch 失效。
- db 默认值用本地 _get_db 惰性代理：deps.get_db 在 deps.py 定义，本模块在 deps.py
  import 阶段被加载，模块级直取会 AttributeError（循环 import 规避）。
- 函数体内 config / resolve_llm_credentials / agentic_writer 装配符号与
  AgenticWriterService 保持函数内 import：patch 目标是源模块（如
  inkflow.infrastructure.agent.agentic_writer），非 deps 命名空间绑定。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module

if TYPE_CHECKING:
    from inkflow.domain.models.agent_run import AgenticWriteRequest
    from inkflow.domain.services.agentic_writer_service import AgenticWriterService


async def _get_db() -> AsyncGenerator[AsyncSession]:
    """deps.get_db 惰性代理（规避 deps ↔ 本模块模块级循环 import）。"""
    from inkflow.api.deps import get_db

    async for session in get_db():
        yield session


def get_agentic_writer_service(
    db: AsyncSession = Depends(_get_db),
) -> AgenticWriterService:
    """获取 AgenticWriterService 实例（agentic 编排，装配 F26/F27 工具）。

    F59-M4（B7）：本轨装配期为同步函数、无 project_id → 装配期只按全局档位解析
    （`project_model=None` 显式声明），作为 `_build_agent` 的兜底值；
    #1298：项目级回退（`项目 config.model > 全局默认`）在 run() 内经 `_agent_factory`
    第二参注入，非空时在此按同一入口重解析 (model, api_key, base_url)。
    """
    from inkflow.api._llm_resolver import resolve_llm_credentials
    from inkflow.core.config import config
    from inkflow.domain.services.agentic_writer_service import AgenticWriterService
    from inkflow.domain.services.model_resolution import resolve_reasoning_effort
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps,
        build_agentic_writer,
        build_writer_agent_system_prompt,
        resolve_writer_authorization,
    )

    # 循环依赖注意：直接 Python 调用无 FastAPI 依赖缓存——内联构建共享同源实例
    draft_service = deps_module.DraftService(
        draft_repo=deps_module.SQLiteDraftRepository(db),
        chapter_service=deps_module.get_chapter_service(db),
        audit_service=deps_module.AuditLogService(deps_module.SQLiteAuditLogRepository(db)),
        memory_service=deps_module.get_memory_service(db),
    )
    audit_service = deps_module.AuditLogService(deps_module.SQLiteAuditLogRepository(db))
    deps = AgenticWriterDeps(
        character_service=deps_module.get_character_service(db),
        foreshadowing_service=deps_module.get_foreshadowing_service(db),
        summary_service=deps_module.get_summary_service(db),
        chapter_audit_service=deps_module.get_chapter_audit_service(db),
        draft_service=draft_service,
        audit_service=audit_service,
        # #1180：world 只读 service 注入（镜像 chat 轨 deps_chat_agent.py:228）
        world_service=deps_module.get_world_service(db),
        # #976 D3（2026-09-06 拍板扩展）：agentic 轨按章 id 反查卷（同 chat 语义）
        volume_lookup=deps_module._make_draft_volume_lookup(db),
    )
    prompt_manager = deps_module.LangChainPromptManager()
    # #1181：写作轨授权（F58 grants + F39 skill 白名单）——内置「写手」Agent 实体同源
    tool_ids, skill_ids = resolve_writer_authorization()

    def _build_agent(request: AgenticWriteRequest, model: str | None = None) -> object:
        """每次 run 构建 agent——系统提示与工具期望上下文按请求注入（#275）.

        #1298：`model` = run() 解析后的模型名（项目 config.model > 全局默认）。
        非空 → 经同一入口 `resolve_llm_credentials(..., project_model=model)` 重解析
        (model, api_key, base_url)，覆盖装配期模块级全局值。
        None/空 → 全局档位兜底：装配期已解析则沿用其值；装配期也解析不到（全局为空，
        已降级为空值）→ 在此按**同一入口** fail-fast 422（#929 零注册表扫描，禁静默
        放行；抛出的 HTTPException 由 writing.py 透传，绝不被改写成 500）。
        """
        system_prompt = build_writer_agent_system_prompt(
            prompt_manager,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
        )
        if model:
            resolved_model, resolved_api_key, resolved_base_url = resolve_llm_credentials(
                config.llm_default_model, project_model=model
            )
        elif default_model:
            # 全局档位兜底（装配期已解析成功，非「假可用」空值）
            resolved_model, resolved_api_key, resolved_base_url = (
                default_model,
                default_api_key,
                default_base_url,
            )
        else:
            # 项目与全局皆空 → 同一入口 fail-fast 422：resolve_chat_model 在最前抛错，
            # 永不触达 provider 查询（#929 零注册表扫描语义不变）
            resolved_model, resolved_api_key, resolved_base_url = resolve_llm_credentials(
                config.llm_default_model, project_model=None
            )
        return build_agentic_writer(
            model=resolved_model,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            deps=deps,
            system_prompt=system_prompt,
            tool_ids=tool_ids,
            skill_ids=skill_ids,
            expected_project_id=request.project_id,
            expected_chapter_id=request.chapter_id,
            reasoning_effort=effort,
        )

    # 模型/密钥/base_url 同源装配（#758 空默认回退首个 chat provider，镜像 #738，防空 key 500）
    # #1298：装配期无 project_id → 显式 project_model=None；项目级回退在 run() 内经
    # _agent_factory 注入（见 _build_agent）。
    # 装配期**不得 fail-fast**：本函数是 FastAPI Depends，先于 endpoint 函数体解析——
    # 全局为空时在此抛 422 会让 run() 永不可达 → 项目级回退永久失效（#1298 核心缺陷）。
    # 故解析失败降级为 ("", "", "") 兜底值：不造「假可用」客户端，空 model 客户端在真实
    # 调用时抛 LLMRequestError（#1269 语义）；422 改由 _build_agent 在同一入口抛。
    try:
        default_model, default_api_key, default_base_url = resolve_llm_credentials(
            config.llm_default_model,
            project_model=None,
        )
    except HTTPException:
        default_model, default_api_key, default_base_url = "", "", ""
    # F59-M4（B7）：全局思考档位（None 项目级 → 全局兜底；全 None → "default"）
    effort = resolve_reasoning_effort(None, None, config.llm_reasoning_effort)

    # #1231/#1232：单章轨接真实数据源——机制与 book 轨（#1200/#1205）**同名同形**，
    # 不另造路径（用户偏好：拒绝同族路径分叉）。
    async def _project_config_getter(project_id: uuid.UUID) -> object | None:
        """项目配置取值（#1231）：`project.config.writing_style` 的真实来源.

        项目不存在 / 取值异常 → None（服务层降级为「不注入风格段」）。
        """
        try:
            project: object | None = await deps_module.get_project_service(db).get(project_id)
        except Exception:  # 配置不可达绝不炸编排
            return None
        return getattr(project, "config", None) if project is not None else None

    async def _chapter_requirements_getter(chapter_id: uuid.UUID) -> str | None:
        """章级写作要求取值（#1232）：`chapters.writing_requirements` 列（GUI 章级栏写入）.

        章不存在 / 列为空 / uuid 溢出等异常 → None（服务层回退请求入参值）。
        实现与 `api/routers/books.py` 的 `_chapter_requirements_getter` 同形。
        """
        try:
            chapter: object | None = await deps_module.get_chapter_service(db).get_chapter(
                chapter_id
            )
        except Exception:  # 列不可达绝不炸编排
            return None
        value = getattr(chapter, "writing_requirements", None) if chapter is not None else None
        return value if isinstance(value, str) and value else None

    return AgenticWriterService(
        agent_factory=_build_agent,
        draft_service=draft_service,
        audit_service=audit_service,
        run_repo=deps_module.SQLiteAgentRunRepository(db),
        chapter_service=deps_module.get_chapter_service(db),
        project_config_getter=_project_config_getter,
        chapter_requirements_getter=_chapter_requirements_getter,
    )
