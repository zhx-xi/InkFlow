"""#1349：AgentService 的「上下文装配」增量方法（F6 上下文注入两部分）。

`agent_service.py` 已贴 900 行护栏，本批把 `_assemble_setting_context` /
`_assemble_continue_context`（同族：设定库注入 + 前文摘要注入）抽至本 mixin
（AGENTS.md monster-file 纪律 + `agent_service_stream.py` 先例）。

领域层约束不变：不 import langchain/langgraph。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from inkflow.domain.models.context import ContextOverride

logger = logging.getLogger(__name__)


class AgentServiceContextMixin:
    """AgentService 的上下文装配方法（与主类同实例装配）。

    依赖由 AgentService.__init__ 注入，此处声明仅为 mypy 可见性
    （mixin 单独检查时无 __init__ 定义）。
    """

    _project_repo: Any
    _character_repo: Any
    _world_repo: Any
    _outline_repo: Any
    _foreshadowing_repo: Any
    _chapter_repo: Any
    _summary_service: Any

    async def _assemble_setting_context(
        self,
        project_id: str,
        variables: dict[str, str],
        override: ContextOverride | None = None,
        injected: dict[str, list[str]] | None = None,
    ) -> dict[str, str]:
        """设定库摘要注入（#366 G1）：角色/伏笔/世界观/大纲四源，非空注入 variables["setting"]。
        单源/整体异常 → WARNING + 回退（失败隔离，不阻断管线）。

        #1319：角色/世界观两源按 override 白名单过滤（#1235 三态：显式 [] = 该源零产出，
        [id...] = 仅命中项）；未显式勾选的源保持全注入（override=None 或该键缺省）。
        #1344：伏笔源同三态（F6 注入集合 = list_open，与 _apply_override 的
        FORESHADOWING 源同源，两路径能力对齐）。
        大纲源无 override 面 → 始终全注入。过滤在该源 try 块内，保持单源失败隔离语义不变。
        #1349：`injected` 传入时就地回填「真正产出条目」的 id 明细（与 setting 同源）。
        """
        if (
            self._character_repo is None
            and self._world_repo is None
            and self._outline_repo is None
            and self._foreshadowing_repo is None
        ):
            return variables
        try:
            project_uuid = uuid.UUID(project_id)
            project_int = project_uuid.int
            project = await self._project_repo.get(project_int)
            if project is None:
                return variables
            parts: list[str] = []
            used_chars: list[str] = []
            used_worlds: list[str] = []
            used_fs: list[str] = []
            if self._character_repo is not None:
                try:
                    characters, _ = await self._character_repo.list(project_uuid, limit=50)
                    # #1319 角色源白名单：仅「显式勾选」通道生效（缺省键 = 该源未覆盖 → 全注入）
                    if override is not None and "character_ids" in override.model_fields_set:
                        allowed = {str(i) for i in override.character_ids}
                        characters = [c for c in characters if str(c.id) in allowed]
                    for ch in characters:
                        content = ch.personality or ch.background or ch.goals
                        if content:
                            parts.append(f"【角色】{ch.name}：{content}")
                            used_chars.append(str(ch.id))  # #1349 回执面
                except Exception:
                    logger.warning("角色设定读取失败，跳过该源", exc_info=True)
            if self._foreshadowing_repo is not None:
                try:
                    # #1344 伏笔源：F6 注入集合 = list_open（status=open，priority DESC）
                    # ——与 ForeshadowingSource.collect（sources.py:249）同源，保证
                    # assemble 预览路径（_apply_override）与本路径产出同一集合。
                    open_fs = await self._foreshadowing_repo.list_open(project_uuid)
                    # #1344 伏笔源白名单：同角色源三态（None/缺省 = 全注入，显式 [] = 删空）
                    if override is not None and "foreshadowing_ids" in override.model_fields_set:
                        allowed_fs = {str(i) for i in override.foreshadowing_ids}
                        open_fs = [f for f in open_fs if str(f.id) in allowed_fs]
                    for f in open_fs:
                        parts.append(
                            f"【伏笔】{f.title}：{f.description}"
                            if f.description
                            else f"【伏笔】{f.title}"
                        )
                        used_fs.append(str(f.id))  # #1349 回执面
                except Exception:
                    logger.warning("伏笔设定读取失败，跳过该源", exc_info=True)
            if self._world_repo is not None:
                try:
                    worlds, _ = await self._world_repo.list(project_uuid, limit=50)
                    # #1319 世界观源白名单：同角色源三态
                    if override is not None and "world_ids" in override.model_fields_set:
                        allowed_worlds = {str(i) for i in override.world_ids}
                        worlds = [ws for ws in worlds if str(ws.id) in allowed_worlds]
                    for ws in worlds:
                        if ws.content:
                            parts.append(f"【世界观】{ws.name}：{ws.content}")
                            used_worlds.append(str(ws.id))  # #1349 回执面
                except Exception:
                    logger.warning("世界观设定读取失败，跳过该源", exc_info=True)
            if self._outline_repo is not None:
                try:
                    outlines, _ = await self._outline_repo.list(project_uuid, limit=50)
                    for o in outlines:
                        if o.description:
                            parts.append(f"【大纲】{o.name}：{o.description}")
                except Exception:
                    logger.warning("大纲设定读取失败，跳过该源", exc_info=True)
            if injected is not None:
                injected["character_ids"] = used_chars
                injected["world_ids"] = used_worlds
                injected["foreshadowing_ids"] = used_fs
            if parts:
                variables["setting"] = "\n\n".join(parts)
        except Exception:
            logger.warning("设定注入失败，回退请求变量", exc_info=True)
        return variables

    async def _assemble_continue_context(
        self,
        project_id: str,
        chapter_id: str | None,
        variables: dict[str, str],
    ) -> dict[str, str]:
        """write_continue 前文摘要注入（#318）：前序 ≤10 章 ensure_summary → variables["context"]；
        任一步失败 → WARNING + 回退（不阻断管线）。
        """
        if self._summary_service is None or not chapter_id:
            return variables
        try:
            pid = uuid.UUID(project_id)
            project = await self._project_repo.get(pid)
            if project is None:
                return variables
            current = await self._chapter_repo.get_chapter(uuid.UUID(chapter_id))
            if current is None:
                return variables
            chapters, _ = await self._chapter_repo.list_chapters(pid, limit=1000)
            prev = sorted(
                (c for c in chapters if c.order_index < current.order_index),
                key=lambda c: c.order_index,
            )[-10:]
            parts: list[str] = []
            for ch in prev:
                try:
                    summary = await self._summary_service.ensure_summary(
                        ch.id, project.config.model
                    )
                except Exception:
                    logger.warning("章节 %s 摘要生成失败，跳过（F6 §4.6）", ch.id)
                    continue
                parts.append(f"{ch.title}：{summary}")
            if parts:
                variables["context"] = "\n\n".join(parts)
        except Exception:
            logger.warning("前文摘要组装失败，回退请求变量", exc_info=True)
        return variables
