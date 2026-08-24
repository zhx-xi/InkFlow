"""F45 M2 语义总结编排 RED 契约测试（全 mock 轨）— 自 test_memory_service_user.py
M2 段拆分（monster file ban 900 行护栏，2026-08-18 父侧拆分）。

依据: specs/f45-memory-evolution/spec.md §5.3（管线）/§5.4（anchor_hash 幂等）/
§5.7（审计）/§9 测试策略第 3 行 ⑪-⑰/§13 M2-3。拆分后本文件自包含：
_project 为复制的 M1 helper（原文件行 217-220），M2 段逐字迁移。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services import preference_learner
from inkflow.domain.services.memory_service import MemoryService

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _project(extra: dict) -> SimpleNamespace:
    """项目鸭子对象（Project.config.extra 语义——F13 先例 dict 读取）."""
    return SimpleNamespace(config=SimpleNamespace(extra=extra))


def _arg(call, name, pos=None, default=None):
    """从 mock call 宽松取参（关键字优先，位置回退）——不锁实现传参形态.

    拆分自 test_memory_service_user.py（原 M1 段 helper，M2 段引用）。
    """
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


def _audit_call(audit_service: AsyncMock, summary: str):
    """返回 audit_service.record 中 severity_summary == summary 的首个 call.

    拆分自 test_memory_service_user.py（原 M1 段 helper，M2 段引用）。
    """
    for c in audit_service.record.await_args_list:
        if _arg(c, "severity_summary", 4) == summary:
            return c
    return None



# ═══ F45 M2 语义总结编排（#340：spec §5.3 管线 / §5.4 anchor_hash 幂等 /
# §5.7 审计 / §9 第 3 行 ⑪-⑰ / §13 M2-3）═══

# ── M2 常量 ──────────────────────────────────────

LLM_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"  # #415 拍板：配置文件唯一默认源


def _anchor(category="style_word", value="低声道") -> SimpleNamespace:
    """锚点鸭子对象（ProjectPreference/UserPreference 语义——category 枚举
    .value 契约，供 preference_learner.anchor_hash 计算）."""
    return SimpleNamespace(category=SimpleNamespace(value=category), value=value)


def _summary_duck(
    *,
    summary_id="sum-1",
    scope="project",
    project_id=PROJECT_ID,
    content="叙述偏好：用角色全名而非代词",
    anchor_hash="hash-1",
    anchor_count=5,
    model=LLM_DEFAULT_MODEL,
    updated_at="2026-08-01T11:00:00+00:00",
) -> SimpleNamespace:
    """语义总结鸭子对象（SemanticSummary 语义——无 model_dump 方法，实现须手动取字段）."""
    return SimpleNamespace(
        id=summary_id,
        scope=scope,
        project_id=project_id,
        content=content,
        anchor_hash=anchor_hash,
        anchor_count=anchor_count,
        model=model,
        updated_at=updated_at,
    )


def _summary_get_side_effect(project_existing, user_existing):
    """summary_repo.get 按 scope 分发（顺序无关——不锁两层调用次序）."""

    def _impl(scope, project_id=None):
        if scope == "project":
            return project_existing
        return user_existing

    return _impl


def _make_m2_service(learner=None, extra=None, *, llm_model=LLM_DEFAULT_MODEL):
    """构造 M2 编排测试服务 + 依赖字典（全鸭子 mock + 真实 preference_learner）.

    learner 缺省 = preference_learner 真实模块（anchor_hash 纯函数契约——
    期望值用真实函数直调计算）；summary_repo/summarizer/llm_default_model
    三新参数注入（RED 阶段构造 TypeError 即预期失败点）。
    """
    deps = {
        "preference_repo": AsyncMock(),
        "event_repo": AsyncMock(),
        "project_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "user_preference_repo": AsyncMock(),
        "summary_repo": AsyncMock(),
        "summarizer": AsyncMock(),
    }
    deps["preference_repo"].list_by_project.return_value = ([], 0)
    deps["preference_repo"].count_by_project.return_value = 0
    deps["project_repo"].get.return_value = _project(extra or {})
    deps["user_preference_repo"].list_all.return_value = ([], 0)
    deps["summary_repo"].get.return_value = None
    deps["summary_repo"].delete_by_project.return_value = 0
    deps["summarizer"].summarize.return_value = (None, 0)
    service = MemoryService(
        preference_repo=deps["preference_repo"],
        event_repo=deps["event_repo"],
        project_repo=deps["project_repo"],
        audit_service=deps["audit_service"],
        learner=learner if learner is not None else preference_learner,
        user_preference_repo=deps["user_preference_repo"],
        summary_repo=deps["summary_repo"],
        summarizer=deps["summarizer"],
        llm_default_model=llm_model,
    )
    return service, deps


class TestMemoryServiceM2Summarize:
    """F45 M2 语义总结编排 RED 契约测试（全 mock 轨，追加于 M1 用例之后）.

    被测模块: memory_service.py 已存在（F28 GREEN + M1 GREEN），M2 扩展
    未实现:
        MemoryService.__init__ 尚不接受 summary_repo/summarizer/
        llm_default_model 关键字参数；get_summaries/summarize 方法不存在；
        preference_learner.anchor_hash 纯函数不存在；
        inkflow.domain.ports.semantic_summary_errors.SemanticSummaryError
        模块不存在（用例体内惰性 import）。

    设计假设（父侧定稿契约，GREEN 按此实现）
    ----------------------------------------
    1. MemoryService 构造扩展: 新增关键字参数 `summary_repo: object | None
       = None`、`summarizer: object | None = None`、`llm_default_model:
       str | None = None`（放 user_preference_repo 之后）:

           def __init__(self, *, preference_repo, event_repo, project_repo,
                        audit_service=None, learner=None,
                        user_preference_repo=None, summary_repo=None,
                        summarizer=None, llm_default_model=None): ...

    2. preference_learner.anchor_hash 纯函数（新建，合法扩展）:

           def anchor_hash(anchors: list) -> str:
               # SHA-256("\n".join(sorted(f"{a.category.value}:{a.value}")))
               # 空列表 → sha256("").hexdigest()

       测试用真实函数计算期望值（import 后直调）——GREEN 实现必须与该公式
       逐字一致（含排序与空列表形态）。

    3. SemanticSummaryError 位于 inkflow.domain.ports.semantic_summary_errors.py
       （API 映射 502，spec §3.3 异常映射表）——用例体内惰性 import（RED
       阶段模块不存在）。

    4. get_summaries（spec §3.2）:

           async def get_summaries(self, project_id) -> dict:
               # 返回 {"project_id": str, "project": {…}|None, "user": {…}|None}
               # 字段: content/anchor_hash/anchor_count/model/updated_at
               #   （实现手动取字段——测试鸭子对象无 model_dump）
               # ① 直接 project_repo.get(project_id.int) 判定（契约裁定：不能
               #    用 is_learning_enabled 合并判定——须区分「项目不存在」与
               #    「开关关闭」两种零行为形态）:
               #    None → summary_repo.delete_by_project(project_id) 清理 +
               #    空结构（spec §7 项目删除级联清理）；
               #    config.extra["memory_learning"]=false → 空结构（零行为，
               #    spec §3.3 200 空）
               # ② 项目层 = summary_repo.get(scope=PROJECT, project_id)；
               #    用户层 = summary_repo.get(scope=USER, None)（全局单一）

    5. summarize（spec §3.2 / §5.4 幂等 + §5.3 管线）:

           async def summarize(self, project_id, *, force: bool = False) -> dict:
               # 返回 {"project_id": str, "summarized": bool,
               #       "project": {…}|None, "user": {…}|None}
               # 项目不存在 → delete_by_project 清理 + summarized=False 空结构；
               # memory_learning=false → summarized=False 空结构（不调 LLM /
               #   不查 summary_repo / 不审计，零行为）
               # 每层独立（顺序: 项目层先、用户层后）:
               #   锚点: 项目级 = preference_repo.list_by_project(project_id)
               #         [0]；用户级 = user_preference_repo.list_all()[0]
               #   哈希: learner.anchor_hash(锚点)
               #   幂等: 既有总结（summary_repo.get）hash 相同且非 force →
               #         复用既有（不调 LLM）；否则调
               #         summarizer.summarize(锚点, scope, project_id,
               #         anchor_hash, model=self._llm_default_model)
               #         （用户层 project_id=None）
               #   落库: 返回 (summary, dropped)；dropped>0 → audit
               #         semantic_summary_failed（degraded=True）；summary
               #         非 None → summary_repo.upsert(summary) 透传产物 +
               #         audit semantic_summary_generated（degraded=True,
               #         actor="memory"）
               # summarized = 任一层真调 LLM 且落库（两层都幂等 → False；
               #   dropped 无产物 → False）
               # 用户级全局单一性: 用户层 project_id=None、锚点哈希用全局
               #   user_preferences（与调用项目无关，spec §5.3）

    6. 测试侧钉死的依赖形态（全鸭子类型，镜像本文件 M1 轨）:
           summary_repo.get(scope, project_id) -> SemanticSummary | None
           summary_repo.upsert(summary) -> SemanticSummary（透传 summarizer 产物）
           summary_repo.delete_by_project(project_id) -> int
           summarizer.summarize(anchors, scope, project_id, anchor_hash,
               model=...) -> (summary | None, dropped)
           preference_repo.list_by_project(project_id) -> (list, int)
           user_preference_repo.list_all() -> (list, int)
           project_repo.get(project_id.int) -> Project | None  # int 背书，F6 先例

    RED 预期
    --------
    memory_service.py 已存在（F28+M1 GREEN），M2 扩展未实现:
    - 全部用例 FAILED（非收集错误）——`_make_m2_service` 传新关键字参数
      summary_repo → `TypeError: MemoryService.__init__() got an unexpected
      keyword argument 'summary_repo'`（规则 1q 签名扩展 TypeError 形态，
      失败点在用例体非收集期）；
    - 若 GREEN 先扩展构造但方法未实现 → 用例体 AttributeError（get_summaries/
      summarize 缺失）；若 preference_learner.anchor_hash 未实现 → 用例体
      AttributeError（anchor_hash 缺失）——均为 FAILED 合法形态；
    - test_summarize_semantic_summary_error_propagates 在 RED 阶段因惰性
      import 模块不存在 → ModuleNotFoundError（用例体 FAILED）。

    asyncio 模式: 沿用本文件 pytestmark（mode=Mode.AUTO 双保险），用例
    async def。
    """

    # ── 契约⑦: get_summaries 零行为 + 项目缺失清理 + 双层返回 ──

    async def test_get_summaries_zero_behavior(self) -> None:
        """契约⑦: memory_learning=false → {"project_id", "project": None,
        "user": None}（零行为空结构，spec §3.3 200 空）——不查 summary_repo."""
        service, deps = _make_m2_service()  # extra 默认 {} → 开关 false
        result = await service.get_summaries(PROJECT_ID)
        assert result == {"project_id": str(PROJECT_ID), "project": None, "user": None}
        deps["summary_repo"].get.assert_not_awaited()
        deps["summary_repo"].delete_by_project.assert_not_awaited()

    async def test_get_summaries_project_missing(self) -> None:
        """契约⑧: project_repo.get 为 None → summary_repo.delete_by_project 被调
        （项目删除级联清理）+ 空结构（project/user 均为 None）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        deps["project_repo"].get.return_value = None
        result = await service.get_summaries(PROJECT_ID)
        assert result == {"project_id": str(PROJECT_ID), "project": None, "user": None}
        deps["summary_repo"].delete_by_project.assert_awaited_once()
        call = deps["summary_repo"].delete_by_project.await_args
        assert str(_arg(call, "project_id", 0)) == str(PROJECT_ID)
        deps["summary_repo"].get.assert_not_awaited()

    async def test_get_summaries_returns_both_layers(self) -> None:
        """契约⑨: mock summary_repo.get 分别返回项目级/用户级 → 两层 dict 字段
        正确（content/anchor_hash/anchor_count/model/updated_at）；get 调用形态
        = 项目层 (scope=project, project_id) + 用户层 (scope=user, None)."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj = _summary_duck(
            summary_id="sum-proj",
            scope="project",
            project_id=PROJECT_ID,
            content="叙述偏好：称呼主角用全名「林晚」而非代词",
            anchor_hash="h-proj",
            anchor_count=5,
            updated_at="2026-08-01T11:00:00+00:00",
        )
        user = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="用户通用风格：句长偏短（≤20 字为主）",
            anchor_hash="h-user",
            anchor_count=12,
            updated_at="2026-08-02T09:30:00+00:00",
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(proj, user)

        result = await service.get_summaries(PROJECT_ID)

        assert result["project_id"] == str(PROJECT_ID)
        assert result["project"]["content"] == "叙述偏好：称呼主角用全名「林晚」而非代词"
        assert result["project"]["anchor_hash"] == "h-proj"
        assert result["project"]["anchor_count"] == 5
        assert result["project"]["model"] == LLM_DEFAULT_MODEL
        assert result["project"]["updated_at"] == "2026-08-01T11:00:00+00:00"
        assert result["user"]["content"] == "用户通用风格：句长偏短（≤20 字为主）"
        assert result["user"]["anchor_hash"] == "h-user"
        assert result["user"]["anchor_count"] == 12
        assert result["user"]["updated_at"] == "2026-08-02T09:30:00+00:00"
        # get 调用形态：项目层 scope=project + project_id；用户层 scope=user + None
        calls = deps["summary_repo"].get.await_args_list
        assert len(calls) == 2
        assert _arg(calls[0], "scope", 0) == "project"
        assert str(_arg(calls[0], "project_id", 1)) == str(PROJECT_ID)
        assert _arg(calls[1], "scope", 0) == "user"
        assert _arg(calls[1], "project_id", 1) is None

    # ── 契约⑩-⑫: summarize 幂等 / 锚点变化 / force ──

    async def test_summarize_idempotent(self) -> None:
        """契约⑩: 既有总结 hash == 当前锚点 hash 且 force=False → summarizer
        不被调用、summarized=False、复用既有内容（spec §5.4 幂等）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("addressing", "林晚"), _anchor("style_word", "低声道")]
        user_anchors = [_anchor("style_word", "低声道"), _anchor("structure", "章节开头用场景描写")]
        proj_hash = preference_learner.anchor_hash(proj_anchors)
        user_hash = preference_learner.anchor_hash(user_anchors)
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, len(proj_anchors))
        deps["user_preference_repo"].list_all.return_value = (user_anchors, len(user_anchors))
        proj_existing = _summary_duck(
            summary_id="sum-proj",
            content="既有项目风格总结",
            anchor_hash=proj_hash,
            anchor_count=2,
        )
        user_existing = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="既有用户风格总结",
            anchor_hash=user_hash,
            anchor_count=2,
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(
            proj_existing, user_existing
        )

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is False
        assert result["project"]["content"] == "既有项目风格总结"
        assert result["project"]["anchor_hash"] == proj_hash
        assert result["user"]["content"] == "既有用户风格总结"
        assert result["user"]["anchor_hash"] == user_hash
        deps["summarizer"].summarize.assert_not_awaited()
        deps["summary_repo"].upsert.assert_not_awaited()

    async def test_summarize_anchor_changed(self) -> None:
        """契约⑪: hash 不同 → summarizer 被调 → upsert 被调 → audit
        semantic_summary_generated → summarized=True（项目层重算、用户层幂等）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        new_hash = preference_learner.anchor_hash(proj_anchors)
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        proj_existing = _summary_duck(
            summary_id="sum-proj",
            content="旧项目总结",
            anchor_hash="old-hash-proj",
            anchor_count=2,
        )
        user_existing = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="旧用户总结",
            anchor_hash=preference_learner.anchor_hash(user_anchors),
            anchor_count=1,
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(
            proj_existing, user_existing
        )
        new_summary = _summary_duck(
            summary_id="sum-proj-new",
            scope="project",
            project_id=PROJECT_ID,
            content="叙述偏好：称呼主角用全名「林晚」而非代词",
            anchor_hash=new_hash,
            anchor_count=1,
        )
        deps["summarizer"].summarize.return_value = (new_summary, 0)

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is True
        assert result["project"]["content"] == "叙述偏好：称呼主角用全名「林晚」而非代词"
        assert result["project"]["anchor_hash"] == new_hash
        deps["summarizer"].summarize.assert_awaited_once()
        call = deps["summarizer"].summarize.await_args
        assert _arg(call, "anchors", 0) == proj_anchors
        assert _arg(call, "scope", 1) == "project"
        assert str(_arg(call, "project_id", 2)) == str(PROJECT_ID)
        assert _arg(call, "anchor_hash", 3) == new_hash
        assert _arg(call, "model", 4) == LLM_DEFAULT_MODEL
        deps["summary_repo"].upsert.assert_awaited_once()
        up_call = deps["summary_repo"].upsert.await_args
        assert _arg(up_call, "summary", 0) is new_summary  # 透传 summarizer 产物
        audit_call = _audit_call(deps["audit_service"], "semantic_summary_generated")
        assert audit_call is not None
        assert _arg(audit_call, "actor", 8) == "memory"
        assert _arg(audit_call, "degraded", 2) is True

    async def test_summarize_force_recomputes(self) -> None:
        """契约⑫: hash 相同但 force=True → 两层均调 summarizer（忽略幂等）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        proj_hash = preference_learner.anchor_hash(proj_anchors)
        user_hash = preference_learner.anchor_hash(user_anchors)
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        proj_existing = _summary_duck(
            summary_id="sum-proj",
            content="项目总结",
            anchor_hash=proj_hash,
            anchor_count=1,
        )
        user_existing = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="用户总结",
            anchor_hash=user_hash,
            anchor_count=1,
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(
            proj_existing, user_existing
        )
        s1 = _summary_duck(
            summary_id="sum-proj-2",
            content="项目总结 v2",
            anchor_hash=proj_hash,
            anchor_count=1,
        )
        s2 = _summary_duck(
            summary_id="sum-user-2",
            scope="user",
            project_id=None,
            content="用户总结 v2",
            anchor_hash=user_hash,
            anchor_count=1,
        )
        deps["summarizer"].summarize.side_effect = [(s1, 0), (s2, 0)]

        result = await service.summarize(PROJECT_ID, force=True)

        assert result["summarized"] is True
        assert deps["summarizer"].summarize.await_count == 2  # 两层都强制重算
        assert deps["summary_repo"].upsert.await_count == 2

    # ── 契约⑬-⑭: dropped 审计 / 用户层全局 ──

    async def test_summarize_hallucination_dropped(self) -> None:
        """契约⑬: summarizer 返回 (None, 2)（防幻觉 B anchor_refs 校验拒绝）→
        audit semantic_summary_failed（degraded=True）+ 不 upsert + summarized=False
        （无产物落库）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        # 项目层幂等（hash 匹配）；用户层 hash 变化 → summarizer 丢弃产物
        proj_existing = _summary_duck(
            summary_id="sum-proj",
            content="项目总结",
            anchor_hash=preference_learner.anchor_hash(proj_anchors),
            anchor_count=1,
        )
        user_existing = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="旧用户总结",
            anchor_hash="old-hash-user",
            anchor_count=1,
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(
            proj_existing, user_existing
        )
        deps["summarizer"].summarize.return_value = (None, 2)

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is False
        assert result["user"] is None
        deps["summary_repo"].upsert.assert_not_awaited()
        audit_failed = _audit_call(deps["audit_service"], "semantic_summary_failed")
        assert audit_failed is not None
        assert _arg(audit_failed, "degraded", 2) is True
        assert _arg(audit_failed, "actor", 8) == "memory"

    async def test_summarize_user_layer_global(self) -> None:
        """契约⑭: 用户级锚点 = user_preference_repo.list_all()（全局 user_preferences）；
        summarizer 收到 scope=USER project_id=None（全局单一性，spec §5.3）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚"), _anchor("style_word", "低声道")]
        user_hash = preference_learner.anchor_hash(user_anchors)
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 2)
        proj_existing = _summary_duck(
            summary_id="sum-proj",
            content="项目总结",
            anchor_hash=preference_learner.anchor_hash(proj_anchors),
            anchor_count=1,
        )
        user_existing = _summary_duck(
            summary_id="sum-user",
            scope="user",
            project_id=None,
            content="旧用户总结",
            anchor_hash="old-hash-user",
            anchor_count=1,
        )
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(
            proj_existing, user_existing
        )
        user_summary = _summary_duck(
            summary_id="sum-user-new",
            scope="user",
            project_id=None,
            content="用户通用风格：句长偏短",
            anchor_hash=user_hash,
            anchor_count=2,
        )
        deps["summarizer"].summarize.return_value = (user_summary, 0)

        result = await service.summarize(PROJECT_ID)

        deps["user_preference_repo"].list_all.assert_awaited_once()
        deps["summarizer"].summarize.assert_awaited_once()
        call = deps["summarizer"].summarize.await_args
        assert _arg(call, "anchors", 0) == user_anchors  # 用户级锚点 = 全局 user_preferences
        assert _arg(call, "scope", 1) == "user"
        assert _arg(call, "project_id", 2) is None  # 用户级全局单一：project_id=None
        assert _arg(call, "anchor_hash", 3) == user_hash
        assert result["summarized"] is True

    # ── 契约⑮-⑰: 零行为 / 审计 / 错误透传 ──

    async def test_summarize_zero_behavior(self) -> None:
        """契约⑮: memory_learning=false → 不调 summarizer/summary_repo →
        空结构 + summarized=False（零行为，spec §7 边界表）."""
        service, deps = _make_m2_service()  # extra 默认 {} → 开关 false
        result = await service.summarize(PROJECT_ID)
        assert result == {
            "project_id": str(PROJECT_ID),
            "summarized": False,
            "project": None,
            "user": None,
        }
        deps["summarizer"].summarize.assert_not_awaited()
        deps["summary_repo"].get.assert_not_awaited()
        deps["summary_repo"].upsert.assert_not_awaited()
        deps["summary_repo"].delete_by_project.assert_not_awaited()
        deps["audit_service"].record.assert_not_awaited()

    async def test_summarize_audit_generated(self) -> None:
        """契约⑯: 成功落库 → audit.record severity_summary="semantic_summary_generated"
        actor="memory"（宽松取参 _arg helper，spec §5.7）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        # 无既有 → 两层都调 LLM
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(None, None)
        s1 = _summary_duck(
            summary_id="sum-p",
            content="项目风格 v1",
            anchor_hash="h1",
            anchor_count=1,
        )
        s2 = _summary_duck(
            summary_id="sum-u",
            scope="user",
            project_id=None,
            content="用户风格 v1",
            anchor_hash="h2",
            anchor_count=1,
        )
        deps["summarizer"].summarize.side_effect = [(s1, 0), (s2, 0)]

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is True
        assert deps["summary_repo"].upsert.await_count == 2
        audit_call = _audit_call(deps["audit_service"], "semantic_summary_generated")
        assert audit_call is not None
        assert _arg(audit_call, "actor", 8) == "memory"
        assert _arg(audit_call, "degraded", 2) is True

    async def test_summarize_semantic_summary_error_propagates(self) -> None:
        """契约⑰: summarizer 抛 SemanticSummaryError → 透传（调用方 API 映射 502，
        spec §3.3 异常映射表）."""
        # 惰性：RED 阶段模块未实现（用例体 FAILED 合法形态）
        from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError

        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(None, None)
        deps["summarizer"].summarize.side_effect = SemanticSummaryError("LLM 调用失败")

        with pytest.raises(SemanticSummaryError):
            await service.summarize(PROJECT_ID)

    # ── coverage 补测（2026-08-18：coverage-backend 门禁 98.5/95.0）──

    async def test_summarize_project_missing_cleans(self) -> None:
        """契约补充: summarize 时 project_repo.get 为 None → delete_by_project 清理 +
        summarized=False 空结构（spec §7 项目删除级联清理，镜像 get_summaries 同语义）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        deps["project_repo"].get.return_value = None

        result = await service.summarize(PROJECT_ID)

        assert result == {
            "project_id": str(PROJECT_ID),
            "summarized": False,
            "project": None,
            "user": None,
        }
        deps["summary_repo"].delete_by_project.assert_awaited()
        deps["summarizer"].summarize.assert_not_awaited()

    async def test_get_summaries_repo_none_defensive(self) -> None:
        """契约补充: get_summaries 时 summary_repo 未注入 → 空结构（防御分支，不炸）."""
        service, _deps = _make_m2_service(extra={"memory_learning": True})
        service._summary_repo = None

        result = await service.get_summaries(PROJECT_ID)

        assert result == {
            "project_id": str(PROJECT_ID),
            "project": None,
            "user": None,
        }

    async def test_summarize_project_layer_dropped_audits(self) -> None:
        """契约补充: 项目层 summarizer 返回 (None, N)（防幻觉丢弃）→ audit
        semantic_summary_failed（degraded=True）+ 项目层不 upsert + summarized=False。"""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        proj_anchors = [_anchor("style_word", "低声道")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = ([], 0)
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(None, None)
        deps["summarizer"].summarize.side_effect = [(None, 2), (None, 0)]

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is False
        assert deps["summary_repo"].upsert.await_count == 0
        failed_call = _audit_call(deps["audit_service"], "semantic_summary_failed")
        assert failed_call is not None
        assert _arg(failed_call, "degraded", 2) is True

    async def test_summarize_repo_or_summarizer_none_defensive(self) -> None:
        """契约补充: summary_repo 或 summarizer 未注入 → 空结构（防御分支，不炸）."""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        # 构造不带 summary_repo/summarizer 的旧形态服务（M1 向后兼容构造）
        service._summary_repo = None
        service._summarizer = None

        result = await service.summarize(PROJECT_ID)

        assert result == {
            "project_id": str(PROJECT_ID),
            "summarized": False,
            "project": None,
            "user": None,
        }
        deps["summarizer"].summarize.assert_not_awaited()

    # ── coverage 补测（2026-08-24：ADR-027 门禁 98.5/95.0 缺口行覆盖）──

    async def test_get_summaries_project_missing_repo_none_skips_delete(self) -> None:
        """覆盖 L719->721: 项目缺失且 summary_repo 未注入 → 跳过 delete_by_project，
        返回空结构（不炸）。"""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        service._summary_repo = None
        deps["project_repo"].get.return_value = None

        result = await service.get_summaries(PROJECT_ID)

        assert result == {"project_id": str(PROJECT_ID), "project": None, "user": None}
        deps["summary_repo"].delete_by_project.assert_not_awaited()

    async def test_summarize_project_missing_repo_none_skips_delete(self) -> None:
        """覆盖 L756->758: summarize 项目缺失且 summary_repo 未注入 → 跳过清理，
        summarized=False 空结构。"""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        service._summary_repo = None
        deps["project_repo"].get.return_value = None

        result = await service.summarize(PROJECT_ID)

        assert result == {
            "project_id": str(PROJECT_ID),
            "summarized": False,
            "project": None,
            "user": None,
        }
        deps["summary_repo"].delete_by_project.assert_not_awaited()

    async def test_summarize_without_audit_service_skips_generated_audit(self) -> None:
        """覆盖 L810->817 + L853->861: audit_service 未注入 → 项目层/用户层落库
        但跳过 semantic_summary_generated 审计（upsert 仍执行）。"""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        service._audit_service = None
        proj_anchors = [_anchor("style_word", "低声道")]
        user_anchors = [_anchor("addressing", "林晚")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["user_preference_repo"].list_all.return_value = (user_anchors, 1)
        deps["summary_repo"].get.side_effect = _summary_get_side_effect(None, None)
        s1 = _summary_duck(summary_id="sum-p", anchor_hash="h1")
        s2 = _summary_duck(
            summary_id="sum-u", scope="user", project_id=None, anchor_hash="h2"
        )
        deps["summarizer"].summarize.side_effect = [(s1, 0), (s2, 0)]

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is True
        assert result["project"] is not None and result["user"] is not None
        assert deps["summary_repo"].upsert.await_count == 2

    async def test_summarize_without_user_repo_skips_user_layer(self) -> None:
        """覆盖 L825->866: user_preference_repo 未注入 → 跳过用户级层
        （仅项目层重算 + 落库），不崩溃。"""
        service, deps = _make_m2_service(extra={"memory_learning": True})
        service._user_preference_repo = None
        proj_anchors = [_anchor("style_word", "低声道")]
        deps["preference_repo"].list_by_project.return_value = (proj_anchors, 1)
        deps["summary_repo"].get.return_value = None
        s1 = _summary_duck(summary_id="sum-p", anchor_hash="h1")
        deps["summarizer"].summarize.return_value = (s1, 0)

        result = await service.summarize(PROJECT_ID)

        assert result["summarized"] is True
        assert result["user"] is None
        assert deps["summary_repo"].upsert.await_count == 1


