"""已学偏好注入源（F6 context sources 数据源之一，spec §5.4）.

PreferenceSource 实时读取已学习的结构化偏好（project_preferences），在 F6
protected 层注入「AI 已记住：{pattern}」条目：
- memory_learning 开关：project.config.extra["memory_learning"] 缺失或 false
  → 零行为（返回 []，验收判据④）
- 冲突规则（Q4=A）：value 是任一显式设定文本的子串 → 跳过该条（显式设定胜）
- 按 count desc 排序，最多注入 10 条（protected 预算防爆）
- 删除立即生效（无缓存）：collect 每次实时查库，读路径无缓存（spec §5.3）
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.preference import ProjectPreference

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
    ) -> None:
        """以两个仓储（可选显式文本加载器）构造注入源."""
        self._preference_repo = preference_repo
        self._project_repo = project_repo
        self._explicit_texts = explicit_texts

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

        result: list[ContextItem] = []
        for pref in sorted(items, key=lambda p: p.count, reverse=True):
            if explicit is not None and any(pref.value in text for text in explicit):
                continue
            result.append(_to_context_item(pref))
            if len(result) >= _MAX_ITEMS:
                break
        return result


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
