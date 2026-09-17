"""#1269 F34 章节审计装配依赖 — 自 deps.py 迁出（防超 900 行护栏）.

deps.py 以 `from inkflow.api.deps_chapter_audit import get_chapter_audit_service`
re-export，routers/chapter_audit.py 与单测仍从 inkflow.api.deps 导入（命名空间不变）。

## 缺陷背景（#1269，P0）

打包产物（隔离数据目录）下章节审计恒 `degraded=True` + `findings=[]`（8/8 章）。
根因：原实现 `llm_client=LangChainLLMClient()` **裸构造**——
`_default_model = default_model or config.llm_default_model`，而隔离目录无
`config.json` / `instance.env` → `config.llm_default_model = ""` →
`parse_model_string("")` 立即抛 `ValueError: Invalid model format: ''`
→ `chapter_audit_service._run_drift_check` 降级（同毫秒失败，非超时）。

**项目级 model（`projects.config.model`）此前从未被审计链消费**——本模块补齐，
对齐写作链 `_llm_resolver.resolve_llm_credentials` 的 project > global 解析链。

## 迁移要点（相对 deps.py 原函数体，行为等价 + 模型解析增强）

- 仓储/服务装配符号经 deps_module（= inkflow.api.deps）**调用期**解析：保持
  单测 patch 目标 `inkflow.api.deps.<名>` 语义（f27 绑定名快照契约先例）。
- 模型/密钥/base_url 装配走 `resolve_llm_credentials` 单一真相（#936 A）：
  project_model > global_default；全空 → 422 + 诊断日志（#929 拍板：绝不静默
  遍历注册表回退，防 embedding 误装配）。
- 语义不变：解析成功后仍由服务层按 spec §5.3 降级（HTTP 200）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module

if TYPE_CHECKING:
    from inkflow.domain.ports.llm_client import LLMClientProtocol
    from inkflow.domain.services.chapter_audit_service import ChapterAuditService


def get_chapter_audit_service(
    db: AsyncSession,
    *,
    project_model: str | None = None,
    resolve_credentials: bool = False,
) -> ChapterAuditService:
    """获取 ChapterAuditService 实例（F34：F1/F2/F9/F10 仓储 + F15 委托 + F5 LLM 检查）。

    Args:
        db: 数据库 session.
        project_model: 项目级模型（`projects.config.model`）；None → 回落全局默认。
        resolve_credentials: 是否在装配期解析模型/凭据（#1269）。

    #1269：审计端点须传 resolve_credentials=True + project_model——裸构造会让
    隔离数据目录（无全局模型）下的审计恒降级（`parse_model_string("")` → ValueError）。
    无解 → 422 + 诊断日志（不静默造出空模型客户端）。

    默认 False = 保留旧语义（#929 R3：`books.py`/agentic 轨装配期不得解析凭据，
    闭包捕获会让项目模型永远不参与）——那些调用点已自行按项目解析。
    """
    llm_client: LLMClientProtocol
    if resolve_credentials:
        from inkflow.api._llm_resolver import resolve_llm_credentials
        from inkflow.core.config import config
        from inkflow.infrastructure.llm import LangChainLLMClient

        model, api_key, base_url = resolve_llm_credentials(
            config.llm_default_model,
            project_model=project_model,
        )
        llm_client = LangChainLLMClient(
            default_model=model,
            api_key=api_key,
            openai_api_base=base_url,
        )
    else:
        from inkflow.infrastructure.llm import LangChainLLMClient

        llm_client = LangChainLLMClient()

    from inkflow.domain.services.chapter_audit_service import ChapterAuditService

    return ChapterAuditService(
        project_repo=deps_module.SQLiteProjectRepository(db),
        chapter_repo=deps_module.SQLiteChapterRepository(db),
        character_repo=deps_module.SQLiteCharacterRepository(db),
        world_repo=deps_module.SQLiteWorldRepository(db),
        audit_service=deps_module.get_audit_service(db),
        llm_client=llm_client,
        audit_log_repo=deps_module.SQLiteAuditLogRepository(db),
    )
