"""F28 M4 注入源 RED 契约测试 — PreferenceSource（fake repo 轨，spec §5.4）.

被测模块（未实现，整模块 RED 形态）:
    from inkflow.infrastructure.context.preference_source import PreferenceSource

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. PreferenceSource（infrastructure/context/preference_source.py 新建，
   镜像 F6 ForeshadowingSource 形态）:

       class PreferenceSource:
           def __init__(
               self,
               preference_repo: object,
               project_repo: object,
               explicit_texts: Callable[[uuid.UUID], Awaitable[list[str]]]
               | None = None,
           ): ...
           async def collect(
               self, project_id: uuid.UUID, chapter_id: uuid.UUID,
           ) -> list[ContextItem]: ...

   语义:
   - project_repo.get(project_id.int) 读 config.extra["memory_learning"]，
     false/缺省 → []
   - 开启 → preference_repo.list_by_project 取偏好（返回 (items, total)）:
     value 是任一 explicit_text 的子串 → 跳过（显式设定胜，Q4 拍板）
   - 最多 10 条（count desc）；content = f"{pattern}（{value}）" 且总长
     ≤200 字符（超长截断/跳过以实现为准，测试锁定 ≤200 与条数 ≤10）
   - title = f"AI 已记住：{pattern}"；source = ContextSourceType.PREFERENCE；
     priority = count；metadata = {"preference_id": str, "category":
     category.value, "count": count}

2. 领域 ProjectPreference/PreferenceCategory（domain/models/preference.py
   新建）——fake preference_repo 返回真实领域对象（镜像
   test_foreshadowing_source.py 构造真实 Foreshadowing 的惯例）。

3. ContextSourceType.PREFERENCE 为 F28 新增枚举值（MODIFY
   domain/models/context.py）——RED 阶段 `ContextSourceType.PREFERENCE`
   取值抛 AttributeError 属预期（被顶部主契约 import 的收集期错误遮蔽）。

RED 预期
--------
收集期失败（整模块 RED 形态: pytest exit 2 / collected 0 items /
1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.context.preference_source'
顶部 import 主契约模块（preference_source）+ 既有 F6/F1 模块
（context.py / project.py）；领域新模型（preference.py）惰性
（_preference helper 内 import）。

asyncio 模式: 本 venv pytest-asyncio mode=Mode.AUTO（pyproject
asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。

F45 M1 追加契约（2026-08-17，spec §5.6/§7/§9）:
- PreferenceSource.__init__ 第 4 可选参 user_preference_repo: object | None
  = None（explicit_texts 之后；F28 既有 3 参构造兼容）→ 存
  self._user_preference_repo
- collect 用户级注入（memory_learning=true 时）: user_preference_repo.
  list_all() → Q1=B 惰性重算（source_projects 含已删项目 → 移除 + 项目数减
  1 + update 写回；project_count<2 → delete）→ Q3=A 冲突过滤（复用
  explicit_texts，项目级/用户级同规则）→ 每条 ContextItem: title=
  「AI 已记住（全局）：{pattern}」/ source=PREFERENCE / content=
  "{pattern}（{value}）"≤200 / priority=count / metadata 含
  preference_id/category/count
- 预算: 项目级 + 用户级合并排序（count desc）最多 10 条（_MAX_ITEMS）；
  user_preference_repo=None → 不注入用户级（向后兼容）
- RED 期构造扩展用属性注入（#318 配方）: source._user_preference_repo =
  fake（构造 4 参 TypeError ERROR 规避）；GREEN 契约 = 构造第 4 参存同名属性
- RED 预期: 用户级 helper 惰性 import UserPreference（模块未实现）→
  ImportError FAILED；模块落地后 → 断言失败（无用户级条目/无全局 title）
  FAILED；守护用例（None 不注入）RED 期即 PASS 刻意（GREEN 后锁行为）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.context.preference_source import PreferenceSource

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID(int=100)
CHAPTER_ID = uuid.UUID(int=2)


def _project(memory_learning: bool | None = None) -> Project:
    """构造项目领域实体（F1 既有模型）；None = extra 无 memory_learning 键."""
    extra = {}
    if memory_learning is not None:
        extra["memory_learning"] = memory_learning
    return Project(
        id=PROJECT_ID,
        name="测试项目",
        config=ProjectConfig(extra=extra),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _preference(pattern, value, *, count, category=None, **kw):
    """构造领域偏好（惰性 import——RED 阶段 domain/models/preference.py 未实现）."""
    # 惰性：RED 阶段模块未实现
    from inkflow.domain.models.preference import PreferenceCategory, ProjectPreference

    values = {
        "id": str(uuid.uuid4()),
        "project_id": PROJECT_ID,
        "category": category if category is not None else PreferenceCategory.ADDRESSING,
        "pattern": pattern,
        "value": value,
        "confidence": 0.7,
        "count": count,
        "source_events": [],
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(kw)
    return ProjectPreference(**values)


class TestPreferenceSourceCollect:
    """PreferenceSource.collect — 开关/冲突过滤/limit/透明标注（spec §5.4）."""

    async def test_returns_empty_when_extra_missing_key(self):
        """开关①: extra 无 memory_learning 键（缺省）→ []（零行为判据④）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project()
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items == []
        preference_repo.list_by_project.assert_not_awaited()

    async def test_returns_empty_when_memory_learning_false(self):
        """开关②: extra["memory_learning"]=False → []."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=False)
        preference_repo = AsyncMock()
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items == []
        preference_repo.list_by_project.assert_not_awaited()

    async def test_returns_empty_when_project_missing(self):
        """开关③: 项目不存在（get → None）→ []（F6 数据源惯例）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = None
        preference_repo = AsyncMock()
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items == []
        preference_repo.list_by_project.assert_not_awaited()

    async def test_returns_empty_when_enabled_but_no_preferences(self):
        """开关④: 开启但无偏好 → []."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items == []

    async def test_project_repo_called_with_int_project_id(self):
        """开关⑤: 以 project_id.int 调 project_repo.get（F1 惯例）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        source = PreferenceSource(preference_repo, project_repo)

        await source.collect(PROJECT_ID, CHAPTER_ID)

        project_repo.get.assert_awaited_once_with(100)
        preference_repo.list_by_project.assert_awaited()
        assert preference_repo.list_by_project.await_args.args[0] == PROJECT_ID

    async def test_builds_context_items_with_full_fields(self):
        """注入①: 开启且有偏好 → 逐条 ContextItem（title/content/source/priority）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [
            _preference("称呼主角为林晚", "林晚", count=3),
            _preference("用词偏好：低声道", "低声道", count=2, category="style_word"),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 2)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 2
        assert all(isinstance(i, ContextItem) for i in items)
        assert [i.source for i in items] == [ContextSourceType.PREFERENCE] * 2
        titles = ["AI 已记住：称呼主角为林晚", "AI 已记住：用词偏好：低声道"]
        assert [i.title for i in items] == titles
        assert [i.priority for i in items] == [3, 2]
        contents = ["称呼主角为林晚（林晚）", "用词偏好：低声道（低声道）"]
        assert [i.content for i in items] == contents

    async def test_skips_preferences_conflicting_with_explicit_texts(self):
        """冲突①: value 命中 explicit_text 子串 → 跳过该条（显式设定胜，Q4）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        explicit_texts = AsyncMock(return_value=["林晚", "第 5 章"])
        prefs = [
            _preference("称呼主角为林晚", "林晚", count=3),
            _preference("用词偏好：低声道", "低声道", count=2),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 2)
        source = PreferenceSource(preference_repo, project_repo, explicit_texts)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 1
        assert items[0].title == "AI 已记住：用词偏好：低声道"
        explicit_texts.assert_awaited()
        assert explicit_texts.await_args.args[0] == PROJECT_ID

    async def test_skips_all_when_all_values_conflict(self):
        """冲突②: 全部 value 命中显式设定 → 空列表."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        explicit_texts = AsyncMock(return_value=["林晚"])
        prefs = [
            _preference("称呼主角为林晚", "林晚", count=3),
            _preference("称呼女主为林晚", "林晚", count=2),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 2)
        source = PreferenceSource(preference_repo, project_repo, explicit_texts)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items == []

    async def test_explicit_texts_optional_when_none(self):
        """冲突③: explicit_texts=None → 不做冲突过滤，全部注入."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [
            _preference("称呼主角为林晚", "林晚", count=3),
            _preference("称呼女主为林晚", "林晚", count=2),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 2)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 2

    async def test_limits_to_10_items(self):
        """limit①: 11 条偏好只注入 10 条（count desc 取前 10，protected 预算防护）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference(f"P{i:02d}", f"V{i:02d}", count=11 - i) for i in range(11)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 11)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 10
        assert [i.priority for i in items] == list(range(11, 1, -1))
        assert "AI 已记住：P10" not in [i.title for i in items]

    async def test_content_format_pattern_value(self):
        """内容①: content = f"{pattern}（{value}）"."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        pref = _preference("称呼主角为林晚", "林晚", count=2)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([pref], 1)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items[0].content == "称呼主角为林晚（林晚）"

    async def test_content_length_limited_to_200(self):
        """内容②: 超长 pattern+value → content 总长 ≤200（截断/跳过以实现为准）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        pref = _preference("长" * 60, "值" * 300, count=2)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([pref], 1)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) <= 1
        if items:
            assert len(items[0].content) <= 200

    async def test_priority_equals_count(self):
        """排序①: priority = count（注入顺序 count desc，fake 按 repo 契约已排序）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [
            _preference("P5", "V5", count=5),
            _preference("P3", "V3", count=3),
            _preference("P1", "V1", count=1),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 3)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert [i.priority for i in items] == [5, 3, 1]

    async def test_title_constant_ai_remembered_prefix(self):
        """标注①: title 恒为「AI 已记住：{pattern}」."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert items[0].title == "AI 已记住：称呼主角为林晚"

    async def test_metadata_carries_preference_fields(self):
        """标注②: metadata = {preference_id, category, count}."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        pref = _preference("称呼主角为林晚", "林晚", count=3)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([pref], 1)
        source = PreferenceSource(preference_repo, project_repo)

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        expected = {
            "preference_id": str(pref.id),
            "category": "addressing",
            "count": 3,
        }
        assert items[0].metadata == expected


# ═══ F45 M1 追加段（2026-08-17，spec §5.6/§7/§9 用户级注入）═══


def _user_preference(pattern, value, *, count, project_count=2, category=None, **kw):
    """构造用户级偏好领域实体（惰性 import——RED 阶段 user_preference.py 未实现）."""
    from inkflow.domain.models.preference import PreferenceCategory
    from inkflow.domain.models.user_preference import UserPreference

    values = {
        "id": str(uuid.uuid4()),
        "category": category if category is not None else PreferenceCategory.STYLE_WORD,
        "pattern": pattern,
        "value": value,
        "confidence": 0.75,
        "count": count,
        "project_count": project_count,
        "source_projects": [str(uuid.UUID(int=101)), str(uuid.UUID(int=102))],
        "source_events": [],
        "created_at": datetime(2026, 8, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    values.update(kw)
    return UserPreference(**values)


class TestPreferenceSourceUserLevel:
    """PreferenceSource.collect 用户级注入（M1，spec §5.6/§7）.

    构造扩展契约: __init__ 第 4 可选参 user_preference_repo: object | None =
    None（explicit_texts 之后，F28 既有 3 参构造兼容）→ 存 self._user_preference_repo。
    RED 期用属性注入（#318 配方）规避构造 TypeError ERROR——source.
    _user_preference_repo = fake 与 GREEN 构造注入同属性名，实现侧按此实现。

    RED 预期: 用户级 helper 惰性 import UserPreference（模块未实现）→
    ImportError FAILED；模块落地后 → 断言失败（无用户级条目/无「AI 已记住
    （全局）」title）FAILED；守护用例（user_preference_repo=None）RED 期即
    PASS 刻意（GREEN 后锁向后兼容）。
    """

    async def test_injects_user_level_preferences_with_global_title(self):
        """⑲ 用户级注入: title=「AI 已记住（全局）：{pattern}」区别于项目级."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=2)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        user_pref = _user_preference("说", "低声道", count=3)
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([user_pref], 1)
        source = PreferenceSource(preference_repo, project_repo)
        source._user_preference_repo = user_repo  # 属性注入（#318 配方）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        titles = [i.title for i in items]
        assert "AI 已记住（全局）：说" in titles  # RED: 用户级不注入 → FAILED
        assert "AI 已记住：称呼主角为林晚" in titles
        user_item = next(i for i in items if i.title.startswith("AI 已记住（全局）"))
        assert user_item.source == ContextSourceType.PREFERENCE
        assert user_item.content == "说（低声道）"
        assert user_item.priority == 3
        assert user_item.metadata == {
            "preference_id": str(user_pref.id),
            "category": "style_word",
            "count": 3,
        }
        user_repo.list_all.assert_awaited_once()

    async def test_user_level_budget_merged_with_project(self):
        """⑳ 预算合并: 项目级 8 + 用户级 5 → 合并排序后最多 10 条."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference(f"P{i:02d}", f"V{i:02d}", count=9 - i) for i in range(1, 9)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 8)
        user_prefs = [_user_preference(f"U{i:02d}", f"W{i:02d}", count=13 - i) for i in range(1, 6)]
        user_repo = AsyncMock()
        user_repo.list_all.return_value = (user_prefs, len(user_prefs))
        source = PreferenceSource(preference_repo, project_repo)
        source._user_preference_repo = user_repo  # 属性注入（#318 配方）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 10  # RED: 用户级缺失 → 仅项目级 8 条 → FAILED
        assert items[0].priority == 12
        assert [i.priority for i in items] == sorted([i.priority for i in items], reverse=True)
        assert "AI 已记住（全局）：U01" in [i.title for i in items]

    async def test_user_level_conflict_filter_skips_value_in_explicit_texts(self):
        """㉑ Q3=A: 用户级 value 命中该项目显式设定文本 → 跳过（同规则）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        explicit_texts = AsyncMock(return_value=["林晚"])
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        user_prefs = [
            _user_preference("她", "林晚", count=5),  # 冲突 → 跳过
            _user_preference("说", "低声道", count=3),  # 不冲突 → 注入
        ]
        user_repo = AsyncMock()
        user_repo.list_all.return_value = (user_prefs, len(user_prefs))
        source = PreferenceSource(preference_repo, project_repo, explicit_texts)
        source._user_preference_repo = user_repo  # 属性注入（#318 配方）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        titles = [i.title for i in items]
        assert "AI 已记住（全局）：说" in titles  # RED: 用户级不注入 → FAILED
        assert "AI 已记住（全局）：她" not in titles
        assert explicit_texts.await_args.args[0] == PROJECT_ID

    async def test_user_level_lazy_recompute_deletes_when_below_two_projects(self):
        """Q1=B 惰性重算①: 移除已删项目后 project_count<2 → delete + 不注入."""
        deleted = uuid.UUID(int=201)
        alive = uuid.UUID(int=202)
        user_pref = _user_preference(
            "说",
            "低声道",
            count=3,
            project_count=2,
            source_projects=[str(deleted), str(alive)],
        )
        project_repo = AsyncMock()
        project_repo.get.side_effect = lambda pid: {
            PROJECT_ID.int: _project(memory_learning=True),
            deleted.int: None,  # 已删项目
            alive.int: _project(memory_learning=True),
        }.get(pid)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([user_pref], 1)
        source = PreferenceSource(preference_repo, project_repo)
        source._user_preference_repo = user_repo  # 属性注入（#318 配方）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        # RED: 用户级逻辑缺失 → delete 未调用 → expected await not found FAILED
        user_repo.delete.assert_awaited()
        assert "AI 已记住（全局）：说" not in [i.title for i in items]

    async def test_user_level_lazy_recompute_updates_when_two_projects_remain(self):
        """Q1=B 惰性重算②: 移除幽灵项目后仍 ≥2 项目 → update 写回 + 继续注入."""
        deleted = uuid.UUID(int=201)
        alive_a = uuid.UUID(int=202)
        alive_b = uuid.UUID(int=203)
        user_pref = _user_preference(
            "说",
            "低声道",
            count=3,
            project_count=3,
            source_projects=[str(deleted), str(alive_a), str(alive_b)],
        )
        project_repo = AsyncMock()
        project_repo.get.side_effect = lambda pid: {
            PROJECT_ID.int: _project(memory_learning=True),
            deleted.int: None,  # 已删项目
            alive_a.int: _project(memory_learning=True),
            alive_b.int: _project(memory_learning=True),
        }.get(pid)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([user_pref], 1)
        source = PreferenceSource(preference_repo, project_repo)
        source._user_preference_repo = user_repo  # 属性注入（#318 配方）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        # RED: 用户级逻辑缺失 → update 未调用 → expected await not found FAILED
        user_repo.update.assert_awaited()
        assert "AI 已记住（全局）：说" in [i.title for i in items]

    async def test_user_preference_repo_none_keeps_project_only(self):
        """守护: user_preference_repo=None（F28 既有 3 参构造）→ 不注入用户级
        （向后兼容；RED 期即 PASS 刻意，GREEN 后锁行为）."""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [
            _preference("称呼主角为林晚", "林晚", count=3),
            _preference("用词偏好：低声道", "低声道", count=2),
        ]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 2)
        source = PreferenceSource(preference_repo, project_repo)  # 既有 3 参构造

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 2
        assert all(not i.title.startswith("AI 已记住（全局）") for i in items)
