"""F45 M2 语义总结注入 RED 契约测试（PreferenceSource M2，全 mock 轨）— 自
test_preference_source.py M2 段拆分（monster file ban 900 行护栏，2026-08-18 父侧拆分）。

依据: specs/f45-memory-evolution/spec.md §5.4/§5.6/§7/§9 M2-4/M2-10。拆分后本文件
自包含：_project/_preference/_user_preference 为复制的 M1 helper（原文件对应行），
M2 段（_semantic_summary/_summary_get_side_effect/_arg/TestPreferenceSourceM2Semantic）
逐字迁移。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.context import ContextSourceType
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.context.preference_source import PreferenceSource

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

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



# ═══ F45 M2 追加段（2026-08-18，spec §5.4/§5.6/§7/§9 M2-4/M2-10 语义总结注入）═══


def _semantic_summary(
    content, *, scope="project", project_id=None, anchor_hash="anchor-hash",
    anchor_count=3, **kw
):
    """构造语义总结领域实体（惰性 import——RED 阶段 semantic_summary.py 未实现）."""
    from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope

    values = {
        "id": str(uuid.uuid4()),
        "scope": SummaryScope.PROJECT if scope == "project" else SummaryScope.USER,
        "project_id": project_id,
        "content": content,
        "anchor_hash": anchor_hash,
        "anchor_count": anchor_count,
        "model": "deepseek/deepseek-v4-flash",
        "created_at": datetime(2026, 8, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 18, tzinfo=UTC),
    }
    values.update(kw)
    return SemanticSummary(**values)


def _summary_get_side_effect(summaries: dict):
    """summary_repo.get 的 side_effect（scope 枚举/字符串双形态兼容）.

    summaries 键为 "project"/"user" 字符串；GREEN 传 SummaryScope 枚举时
    经 getattr(scope, "value", scope) 归一；project_id 参数不参与分发。
    """

    def _get(*args, **kwargs):
        scope = kwargs.get("scope") if "scope" in kwargs else (args[0] if args else None)
        return summaries.get(getattr(scope, "value", scope))

    return _get


def _arg(call, name: str, index: int, default=None):
    """宽松取参：位置或关键字（规则 1o 同款，兼容两种 GREEN 传参形态）."""
    args, kwargs = call.await_args
    return args[index] if len(args) > index else kwargs.get(name, default)


class TestPreferenceSourceM2Semantic:
    """PreferenceSource.collect M2 语义总结优先注入（spec §5.6/§5.4/§7；验收 M2-4/M2-10）.

    构造扩展契约（父侧定稿，GREEN 按此实现）: __init__ 在第 4 参
    user_preference_repo 之后追加 4 个可选参数，全部默认 None:

        def __init__(
            self,
            preference_repo: object,
            project_repo: object,
            explicit_texts: ... | None = None,
            user_preference_repo: object | None = None,
            summary_repo: object | None = None,        # M2: get/upsert
            summarizer: object | None = None,          # M2: summarize → (s, dropped)
            llm_default_model: str | None = None,      # M2: config.llm_default_model（#415）
            background_refresh: object | None = None,  # M2: F44 阶段4 后台刷新回调
        ): ...

    collect M2 流程（语义总结优先，spec §5.6）:
    1. memory_learning=false → []（既有零行为）
    2. 既有 M1 项目级/用户级字面收集逻辑保持（冲突过滤 + 用户级惰性重算）
    3. summary_repo 且 summarizer 注入时（双非 None）:
       a. project_summary = summary_repo.get(scope=PROJECT, project_id=project_id)
          user_summary = summary_repo.get(scope=USER, project_id=None)
       b. project_hash = anchor_hash(项目级 items)；user_hash = anchor_hash(用户级
          items)——SHA-256 排序锚点键（spec §5.4）；测试不引用 anchor_hash 符号，
          既有总结 anchor_hash 用固定串 → 与当前锚点哈希必然不同（触发路径）
       c. 某层 hash ≠ 既有总结 hash 或无总结 → 锚点变化:
          - background_refresh is None（F44 阶段4 未就位）→ 同步总结兜底:
            summarizer.summarize(items, scope, project_id, anchor_hash,
            model=llm_default_model) → (summary, dropped)
            summary 非 None → summary_repo.upsert(summary) + 注入新总结
            summary 为 None → 保留旧总结/字面兜底
            SemanticSummaryError（LLM 失败）→ 捕获不阻断，回退旧总结/字面
          - background_refresh 注入（F44 阶段4 就位）→ 旧总结注入 + 审计
            pending_summary（degraded=True, actor="memory"）+ 调 background_refresh
    4. 注入: 有项目级总结 → ContextItem(title="🧠 项目风格：", content=总结 content
       截断 ≤200, source=PREFERENCE, priority=anchor_count)；有用户级总结 →
       title="🧠 通用风格："；总结存在时只注入总结不混字面；某层无总结 → 该层
       回退字面（_to_context_item/_to_user_context_item）
    5. 预算: 总条目 ≤10（_MAX_ITEMS）延续；总结条目不过 Q4 冲突过滤（抽象指令）

    审计注入契约: PreferenceSource 以实例属性 _audit 承载审计回调（None = 跳过，
    F28 异常静默旁路语义）；RED 期属性注入 source._audit = AsyncMock()（M1 #318
    同款配方）；GREEN 构造默认 self._audit = None，pending_summary 路径调用
    await self._audit(event="pending_summary", degraded=True, actor="memory")。

    语义总结领域实体（domain/models/semantic_summary.py，spec §2.3，未实现）:
    SummaryScope.PROJECT="project"/USER="user"；SemanticSummary 字段
    id/scope/project_id/content/anchor_hash/anchor_count/model/created_at/updated_at
    ——helper _semantic_summary 惰性 import（RED 期模块未实现 → ModuleNotFoundError）。

    RED 预期（本批选「构造 TypeError」主形态）: 除 test_llm_failure_falls_back
    外 7 用例在用例体构造行 PreferenceSource(..., summary_repo=...) → TypeError
    （unexpected keyword argument 'summary_repo'）→ 用例 FAILED（用例体异常 =
    FAILED 非 ERROR）；test_llm_failure_falls_back 用例体首行惰性 import
    SemanticSummaryError → ModuleNotFoundError FAILED（先于构造行）；GREEN 构造
    扩展落地后 → 断言语义驱动。备选形态（未采用）: helper 惰性 import
    SemanticSummary → ModuleNotFoundError FAILED——本批按父侧契约直接锁构造参数
    扩展。test_lazy_summary_* 两用例被 `-k lazy_summary`（验收 M2-10）命中。
    """

    async def test_project_summary_injected_first(self):
        """㉒ M2 注入①: 项目级总结存在 → title「🧠 项目风格：」+ content == 总结
        content，且不注入字面条目（总结优先，spec §5.6 步骤 4）。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        project_summary = _semantic_summary(
            "叙述偏好：用角色全名而非代词", scope="project", project_id=PROJECT_ID,
            anchor_count=5,
        )
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"project": project_summary})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (project_summary, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        titles = [i.title for i in items]
        assert any("🧠 项目风格：" in t for t in titles)  # RED: 构造 TypeError → FAILED
        summary_item = next(i for i in items if "🧠 项目风格" in i.title)
        assert summary_item.content == project_summary.content
        assert all("AI 已记住" not in t for t in titles)  # 总结存在时不混字面

    async def test_user_summary_title(self):
        """㉓ M2 注入②: 用户级总结存在 → title「🧠 通用风格：」区分归属
        （spec §5.6 归属可视化——用户可辨「学到了什么、从哪学来」）。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        user_summary = _semantic_summary("句长偏短，避免冗余修饰", scope="user", anchor_count=12)
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"user": user_summary})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (user_summary, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert any("🧠 通用风格：" in i.title for i in items)  # RED: 构造 TypeError → FAILED
        user_item = next(i for i in items if "🧠 通用风格" in i.title)
        assert user_item.content == user_summary.content
        assert user_item.source == ContextSourceType.PREFERENCE

    async def test_fallback_to_literal_without_summary(self):
        """㉔ M2 兜底①: summary_repo 无总结 + summarizer 注入 → 回退 M1 字面
        （title「AI 已记住：」/「AI 已记住（全局）：」，保底不丢失记忆）。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        user_pref = _user_preference("说", "低声道", count=2)
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([user_pref], 1)
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (None, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            user_repo,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        titles = [i.title for i in items]
        assert "AI 已记住：称呼主角为林晚" in titles  # RED: 构造 TypeError → FAILED
        assert "AI 已记住（全局）：说" in titles
        assert all("🧠" not in t for t in titles)

    async def test_lazy_summary_sync_summary_on_anchor_change(self):
        """㉕ M2 两段式①（-k lazy_summary 命中，验收 M2-10）: 锚点变化 +
        background_refresh=None（F44 阶段4 未就位）→ 同步总结兜底: summarizer
        被调（scope=project）+ upsert 被调 + 注入新总结 content。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        old_summary = _semantic_summary(
            "旧总结内容", scope="project", project_id=PROJECT_ID, anchor_hash="old-hash"
        )
        new_summary = _semantic_summary(
            "叙述偏好：用角色全名而非代词", scope="project", project_id=PROJECT_ID,
            anchor_hash="new-hash", anchor_count=5,
        )
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"project": old_summary})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (new_summary, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        summarizer.summarize.assert_awaited()  # RED: 构造 TypeError → FAILED
        scope = _arg(summarizer.summarize, "scope", 1)
        assert getattr(scope, "value", scope) == "project"
        assert _arg(summarizer.summarize, "project_id", 2) == PROJECT_ID
        summary_repo.upsert.assert_awaited()
        assert items[0].content == new_summary.content

    async def test_lazy_summary_background_refresh_path(self):
        """㉖ M2 两段式②（-k lazy_summary 命中，验收 M2-10）: 锚点变化 +
        background_refresh 注入（F44 阶段4 就位）→ 旧总结注入（不等待 LLM）+
        audit pending_summary（degraded=True, actor="memory"）+ background_refresh
        以单个 coroutine 实参被调（位置/关键字皆可）；summarizer 不被调。"""
        import inspect

        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        old_summary = _semantic_summary(
            "旧总结内容", scope="project", project_id=PROJECT_ID, anchor_hash="old-hash"
        )
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"project": old_summary})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (old_summary, [])
        background_refresh = AsyncMock()
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
            background_refresh=background_refresh,
        )
        source._audit = AsyncMock()  # 审计回调属性注入（类 docstring 审计契约）

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        summarizer.summarize.assert_not_awaited()  # RED: 构造 TypeError → FAILED
        summary_item = next(i for i in items if "🧠 项目风格" in i.title)
        assert summary_item.content == old_summary.content  # 旧总结注入（零阻塞）
        source._audit.assert_awaited()
        assert _arg(source._audit, "event", 0) == "pending_summary"
        assert _arg(source._audit, "degraded", 2) is True
        assert _arg(source._audit, "actor", 1) == "memory"
        background_refresh.assert_awaited()
        args, kwargs = background_refresh.await_args
        coro = args[0] if args else next(iter(kwargs.values()), None)
        assert inspect.iscoroutine(coro)

    async def test_llm_failure_falls_back(self):
        """㉗ M2 兜底②: summarizer.summarize 抛 SemanticSummaryError（LLM 失败）
        → collect 不抛错、回退旧总结注入（有既有总结时），不阻断注入。"""
        from inkflow.domain.services.semantic_summarizer import SemanticSummaryError

        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        prefs = [_preference("称呼主角为林晚", "林晚", count=3)]
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = (prefs, 1)
        old_summary = _semantic_summary(
            "旧总结内容", scope="project", project_id=PROJECT_ID, anchor_hash="old-hash"
        )
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"project": old_summary})
        summarizer = AsyncMock()
        summarizer.summarize.side_effect = SemanticSummaryError("LLM 总结失败")
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)  # 不抛错

        assert len(items) >= 1
        summary_item = next(i for i in items if "🧠 项目风格" in i.title)
        assert summary_item.content == old_summary.content  # 旧总结回退（LLM 失败不阻断）

    async def test_user_scope_sync_summary(self):
        """㉘ M2 用户级①: 用户级锚点变化（无既有用户总结）→ summarizer 收到
        scope=user + project_id=None（用户级总结全局单一性，spec §5.3）。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        user_pref = _user_preference("说", "低声道", count=3)
        user_repo = AsyncMock()
        user_repo.list_all.return_value = ([user_pref], 1)
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({})
        new_summary = _semantic_summary("句长偏短", scope="user", anchor_count=12)
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (new_summary, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            user_repo,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        summarizer.summarize.assert_awaited()  # RED: 构造 TypeError → FAILED
        scope = _arg(summarizer.summarize, "scope", 1)
        assert getattr(scope, "value", scope) == "user"
        assert _arg(summarizer.summarize, "project_id", 2) is None
        assert any("🧠 通用风格" in i.title for i in items)

    async def test_summary_content_truncated_200(self):
        """㉙ M2 预算①: 总结 content 超 200 字符 → 注入 content 截断 ≤200
        （F28 预算防护延续，spec §5.6 步骤 6）。"""
        project_repo = AsyncMock()
        project_repo.get.return_value = _project(memory_learning=True)
        preference_repo = AsyncMock()
        preference_repo.list_by_project.return_value = ([], 0)
        long_summary = _semantic_summary(
            "叙述偏好" * 60, scope="project", project_id=PROJECT_ID, anchor_count=5
        )
        summary_repo = AsyncMock()
        summary_repo.get.side_effect = _summary_get_side_effect({"project": long_summary})
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (long_summary, [])
        source = PreferenceSource(
            preference_repo,
            project_repo,
            None,
            None,
            summary_repo=summary_repo,
            summarizer=summarizer,
            llm_default_model="deepseek/deepseek-v4-flash",
        )

        items = await source.collect(PROJECT_ID, CHAPTER_ID)

        assert len(items) == 1  # RED: 构造 TypeError → FAILED
        assert len(items[0].content) <= 200
