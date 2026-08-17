"""已学偏好注入源（F6 context sources 数据源之一，spec §5.4）.

PreferenceSource 实时读取已学习的结构化偏好（project_preferences），在 F6
protected 层注入「AI 已记住：{pattern}」条目：
- memory_learning 开关：project.config.extra["memory_learning"] 缺失或 false
  → 零行为（返回 []，验收判据④）
- 冲突规则（Q4=A）：value 是任一显式设定文本的子串 → 跳过该条（显式设定胜）
- 按 count desc 排序，最多注入 10 条（protected 预算防爆）
- 删除立即生效（无缓存）：collect 每次实时查库，读路径无缓存（spec §5.3）
- M1 用户级注入（spec §5.6）：user_preferences 合并进预算（title 前缀
  「AI 已记住（全局）：」区分归属；Q3=A 同规则冲突过滤；Q1=B 惰性重算）
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.preference import ProjectPreference
from inkflow.domain.models.user_preference import UserPreference

# 单次注入上限（protected 预算防爆，spec §5.4）
_MAX_ITEMS = 10
# 单条内容长度上限（字符，超长截断到 200）
_MAX_CONTENT_LEN = 200


class PreferenceSource:
    """已学偏好注入源（spec §5.4）— F6 context sources 数据源之一.

    Args:
        preference_repo: 偏好仓储（list_by_project）.
        project_repo: 项目仓储（get(int) 读 config.extra）.
        explicit_texts: 显式设定文本加载器（Q4 冲突过滤；None = 不加载）.
    """

    def __init__(
        self,
        preference_repo: object,
        project_repo: object,
        explicit_texts: Callable[[uuid.UUID], Awaitable[list[str]]] | None = None,
        user_preference_repo: object | None = None,
    ) -> None:
        """以两个仓储（可选显式文本加载器 / 用户级偏好仓储）构造注入源."""
        self._preference_repo = preference_repo
        self._project_repo = project_repo
        self._explicit_texts = explicit_texts
        self._user_preference_repo = user_preference_repo

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        """收集已学偏好注入条目（开关 + 冲突过滤 + 上限 10 条）.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（MVP 不使用，仅接口对齐 F6 数据源）.

        Returns:
            注入的 ContextItem 列表；项目缺失 / 未开启 / 无偏好 → []（零行为，
            验收判据④）.
        """
        project = await self._project_repo.get(project_id.int)  # type: ignore[attr-defined]  # 结构化鸭子类型：ProjectRepositoryProtocol.get(int)
        if project is None or not project.config.extra.get("memory_learning"):
            return []

        items, _total = await self._preference_repo.list_by_project(project_id)  # type: ignore[attr-defined]  # 结构化鸭子类型：偏好仓储 list_by_project(project_id)

        explicit: list[str] | None = None
        if self._explicit_texts is not None:
            explicit = await self._explicit_texts(project_id)

        # 项目级（F28 既有语义：冲突过滤收集；排序/limit 移到合并后统一处理）
        project_items: list[ProjectPreference] = []
        for pref in sorted(items, key=lambda p: p.count, reverse=True):
            if explicit is not None and any(pref.value in text for text in explicit):
                continue
            project_items.append(pref)

        # ── M1 用户级注入（spec §5.6/§7，Q1=B 惰性重算 + Q3=A 冲突过滤）──
        user_items: list[UserPreference] = []
        if self._user_preference_repo is not None:
            user_items_all, _utotal = await self._user_preference_repo.list_all()  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约返回 (items, total) 元组
            for up in user_items_all:
                ghost: list[str] = []
                for pid_str in up.source_projects:
                    try:
                        pid = uuid.UUID(pid_str)
                    except ValueError:
                        continue
                    proj = await self._project_repo.get(pid.int)  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get
                    if proj is None:
                        ghost.append(pid_str)
                if ghost:
                    new_projects = [p for p in up.source_projects if p not in ghost]
                    new_project_count = up.project_count - len(ghost)
                    if new_project_count < 2:
                        await self._user_preference_repo.delete(up.id)  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 delete
                        continue
                    await self._user_preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 update
                        up.id,
                        count=up.count,
                        confidence=up.confidence,
                        project_count=new_project_count,
                        source_projects=new_projects,
                        source_events=up.source_events,
                    )
                if explicit is not None and any(up.value in text for text in explicit):
                    continue  # Q3=A：用户级同规则冲突过滤
                user_items.append(up)

        # 合并排序取前 10（F28 项目级行为等价：排序 + limit 相同）
        combined: list[ProjectPreference | UserPreference] = [*project_items, *user_items]
        combined.sort(key=lambda p: p.count, reverse=True)
        return [
            _to_context_item(p) if isinstance(p, ProjectPreference) else _to_user_context_item(p)
            for p in combined[:_MAX_ITEMS]
        ]


def _to_context_item(pref: ProjectPreference) -> ContextItem:
    """偏好领域实体 → 注入条目（title/content/metadata 确定性模板，无 LLM）.

    Args:
        pref: 一条已学习偏好.

    Returns:
        ContextItem：content = "{pattern}（{value}）"，总长 > 200 字符时截断到 200；
        priority = count；metadata 携带 preference_id/category/count.
    """
    content = f"{pref.pattern}（{pref.value}）"
    if len(content) > _MAX_CONTENT_LEN:
        content = content[:_MAX_CONTENT_LEN]
    return ContextItem(
        source=ContextSourceType.PREFERENCE,
        title=f"AI 已记住：{pref.pattern}",
        content=content,
        priority=pref.count,
        metadata={
            "preference_id": str(pref.id),
            "category": pref.category.value,
            "count": pref.count,
        },
    )


def _to_user_context_item(pref: UserPreference) -> ContextItem:
    """用户级偏好领域实体 → 注入条目（title「AI 已记住（全局）：{pattern}」区分归属，spec §5.6 M1）.

    Args:
        pref: 一条已学习用户级偏好.

    Returns:
        ContextItem：content = "{pattern}（{value}）"，总长 > 200 字符时截断到 200；
        priority = count；metadata 携带 preference_id/category/count.
    """
    content = f"{pref.pattern}（{pref.value}）"
    if len(content) > _MAX_CONTENT_LEN:
        content = content[:_MAX_CONTENT_LEN]
    return ContextItem(
        source=ContextSourceType.PREFERENCE,
        title=f"AI 已记住（全局）：{pref.pattern}",
        content=content,
        priority=pref.count,
        metadata={
            "preference_id": str(pref.id),
            "category": pref.category.value,
            "count": pref.count,
        },
    )
