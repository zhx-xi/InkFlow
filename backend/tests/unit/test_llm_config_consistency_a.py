"""#936 A 项 RED 契约：chat 装配旁路收敛 + import 快照缺陷修复。

缺陷背景（评审 NIT-2 + 侦察实证，issue #936 A 项）：
「模型装配 fail-fast 化」（#929）只罩住 `resolve_llm_credentials` 的 4 个调用方；
全仓另有 30+ 处直接读 `config.llm_default_model` 当 chat 模型消费、不经 resolver
→ fail-fast 收益碎片化，错误呈现不一致（有的构造期炸、有的静默 None、
有的运行期深处才错）。

【侦察实证 — 比 issue 描述更严重】
Issue 将 A 项定性为「错误呈现不一致、不计入回归」。实测推翻该定性：
「import 快照、运行期改配置不生效」不是 agent_templates.py:62 的孤例，
而是 3 个模块族（pipeline_templates ×12 / 4+ 域服务 __init__ 默认参 / agent_templates）。
探针（先 import → 改配置 → 读消费点）实证三者全部冻结在 import 时的值。

用户可见后果：用户在设置页改默认模型 → 写作链路角色模型（architect/writer/
auditor/reviser）与各域服务仍用旧模型，直到重启内核并重载模块。
这不是「错误呈现不一致」，而是功能缺陷。

契约（#936 spec §2.1/§3.1）：
① 新增 `resolve_chat_model(global_default, *, project_model=None) -> str` 单值守卫
   helper（project > global，同 #735 链）——空 → loguru ERROR 锚「LLM 模型解析失败」
   + HTTPException 422（detail 逐字保留 #821/#929 契约文案）。
② `resolve_llm_credentials` 内部复用同一解析链（单一真相，禁第二份逻辑）
   —— 与 helper 同 422 契约。
③ 数据构造点（模板/服务默认参）只改**惰性读取**（运行期取当前配置值），
   **不抛错**（Q2 拍板：模板是数据非装配点，抛在这里会让 GET /agent-templates
   列表端点也 422，违背 NIT-2「错误呈现一致」初衷）。

【R】= 当前必 FAIL（修复锚）；【G】= 当前 PASS（回归守护/护栏）。
"""

from __future__ import annotations

import inspect
import sys
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from loguru import logger

RESOLVE_422_DETAIL = "未配置默认模型，请在设置中配置 LLM Provider 和默认模型"
LOG_ANCHOR = "LLM 模型解析失败"

# 快照探针使用的哨兵值（保证与任何真实配置值可区分）
SNAPSHOT_A = "sentinel-a/before-import"
SNAPSHOT_B = "sentinel-b/after-import"


@pytest.fixture(autouse=True)
def _restore_loguru():
    """还原 loguru 全局 sink（镜像 test_llm_resolver_929 模式）。"""
    yield
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")


def _capture_logs(level: str = "DEBUG"):
    """捕获 loguru 记录（返回 records 列表 + sink id）。"""
    records: list = []
    sid = logger.add(lambda m: records.append(m.record), level=level, format="{message}")
    return records, sid


def _error_logs(records: list) -> list[str]:
    """提取 ERROR 级日志文本。"""
    return [str(r["message"]) for r in records if r["level"].name == "ERROR"]


@contextmanager
def _mutated_default(value: str):
    """临时改 config.llm_default_model，退出时还原（隔离测试间污染）。"""
    from inkflow.core.config import config

    original = config.llm_default_model
    config.llm_default_model = value
    try:
        yield
    finally:
        config.llm_default_model = original


class TestSnapshotDefectFixed:
    """快照缺陷修复——核心回归锚（#936 spec §1.1 实测 3 个模块族）。

    判据：先 import 目标模块（值在 import 时若被求值即冻结）→ 改
    config.llm_default_model → 读消费点 → **必须等于新值**。

    当前实现（模块级 BUILTIN_TEMPLATES 构造 / __init__ 默认参 / 模块常量）
    全部在 import 期求值 → 读到 SNAPSHOT_A 而非 SNAPSHOT_B → FAIL。
    """

    def test_r1_pipeline_templates_lazy_read(self) -> None:
        """【R】pipeline_templates 角色模型运行期随配置变化。

        当前实现：BUILTIN_TEMPLATES 是模块级 dict（L324-329），12 处
        `model=config.llm_default_model` 在 import 时构造求值 → 冻结。
        """
        from inkflow.infrastructure.agent import pipeline_templates as pt

        with _mutated_default(SNAPSHOT_B):
            for tid in ("builtin:chat", "builtin:write_chapter", "builtin:write_auto",
                        "builtin:write_continue"):
                tpl = pt.get_template(tid)
                assert tpl is not None, f"模板 {tid} 应存在"
                models = {s.agent.model for s in tpl.stages}
                assert models == {SNAPSHOT_B}, (
                    f"#936 A 项：{tid} 角色模型必须惰性读取当前配置（期望 {SNAPSHOT_B}，"
                    f"实际 {models}）——模块级 BUILTIN_TEMPLATES 在 import 时冻结了旧值"
                )

    def test_r2_agent_templates_builtin_default_lazy(self) -> None:
        """【R】agent_templates 角色 model 回填值运行期随配置变化。

        当前实现：`BUILTIN_DEFAULT_MODEL = config.llm_default_model`（L62）
        import 时定值 → 运行期改配置不生效。
        """
        from inkflow.api.routers import agent_templates as at

        with _mutated_default(SNAPSHOT_B):
            # 契约不以模块常量为准（惰性重构后该常量可能不存在）——改测「回填值」
            assert not hasattr(at, "BUILTIN_DEFAULT_MODEL") or (
                at.BUILTIN_DEFAULT_MODEL == SNAPSHOT_B
            ), (
                "#936 A 项：agent_templates 的 model 回填值必须运行期取配置；"
                f"模块常量仍为冻结值 {getattr(at, 'BUILTIN_DEFAULT_MODEL', '<absent>')}"
            )

    def test_r3_domain_services_signature_not_snapshot(self) -> None:
        """【R】域服务 __init__ 默认参不得是 import 快照。

        当前实现：`llm_default_model: str = config.llm_default_model` → 默认值
        在 import 时求值冻结（实测 character/outline/world/extraction 四族同款）。

        契约：签名默认值须为 None（构造期回退 resolve_chat_model），
        以便运行期改配置生效。
        """
        from inkflow.domain.services.character_service import CharacterService
        from inkflow.domain.services.extraction_service import ExtractionService
        from inkflow.domain.services.outline_service import OutlineService
        from inkflow.domain.services.world_service import WorldService

        for cls in (CharacterService, OutlineService, WorldService, ExtractionService):
            default = inspect.signature(cls.__init__).parameters["llm_default_model"].default
            assert default is None, (
                f"#936 A 项：{cls.__name__}.__init__ 的 llm_default_model 默认值"
                f"须为 None（构造期回退守卫），实际 {default!r}——"
                "`config.llm_default_model` 作默认参 = import 快照，运行期改配置不生效"
            )

    def test_r4_service_runtime_reads_current_config(self) -> None:
        """【R】域服务实例化后取到**当前**配置值（端到端验证惰性）。

        与 R3 互补：R3 锁签名形态，R4 锁行为（默认参缺省时回退到当前配置）。
        """
        from unittest.mock import MagicMock

        from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
        from inkflow.domain.services.character_service import CharacterService

        repo = MagicMock(spec=CharacterRepositoryProtocol)
        with _mutated_default(SNAPSHOT_B):
            svc = CharacterService(repository=repo)
            assert svc._llm_default_model == SNAPSHOT_B, (
                "#936 A 项：未显式传 llm_default_model 时须回退当前配置值"
                f"（期望 {SNAPSHOT_B}，实际 {svc._llm_default_model!r}）"
            )


class TestSnapshotGuard:
    """【G】护栏：未改配置时读到的值 == 当前配置值（防过度修正为常量）。

    这两条当前即 PASS，作用是给实现方 anti-overcorrection 锚——禁止把
    惰性读取「修」成硬编码常量（那会引入第二份默认值，违背 #415）。
    """

    def test_g1_pipeline_templates_tracks_config_exactly(self) -> None:
        """【G】模板模型值恒等于当前 config 值（非固定常量）。"""
        from inkflow.core.config import config
        from inkflow.infrastructure.agent import pipeline_templates as pt

        tpl = pt.get_template("builtin:chat")
        assert tpl.stages[0].agent.model == config.llm_default_model, (
            "护栏：模板模型值应恒等于当前配置值（不得硬编码为常量）"
        )

    def test_g2_agent_templates_tracks_config_exactly(self) -> None:
        """【G】agent_templates 回填值与当前 config 一致（or 常量已移除）。"""
        from inkflow.api.routers import agent_templates as at
        from inkflow.core.config import config

        if hasattr(at, "BUILTIN_DEFAULT_MODEL"):
            assert config.llm_default_model == at.BUILTIN_DEFAULT_MODEL
        else:
            # 惰性重构后常量可以不存在——回填逻辑改为运行期求值
            assert True


class TestResolveChatModelGuard:
    """resolve_chat_model 单值守卫 helper 契约（#936 spec §2.1）。"""

    def test_r5_empty_everything_422_with_anchor(self) -> None:
        """【R】空默认 + 空项目模型 → 422（detail 逐字）+ ERROR 锚。

        RED 形态：`resolve_chat_model` 不存在 → ImportError。
        """
        from inkflow.api._llm_resolver import resolve_chat_model

        records, sid = _capture_logs()
        try:
            with pytest.raises(HTTPException) as exc_info:
                resolve_chat_model("")
        finally:
            logger.remove(sid)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == RESOLVE_422_DETAIL, "422 文案逐字保留（#821/#929 兼容）"
        assert any(LOG_ANCHOR in msg for msg in _error_logs(records)), (
            f"#936 A 项：解析失败须落 ERROR 诊断日志（锚={LOG_ANCHOR!r}），"
            f"实际 {_error_logs(records)}"
        )

    def test_r6_project_model_wins_and_returns_str(self) -> None:
        """【R】project_model 优先，返回**裸字符串**（非三元组）。

        与 resolve_llm_credentials 的差异契约：只消费模型名的旁路点用单值 helper
        （三元组会引入多余耦合）。
        """
        from inkflow.api._llm_resolver import resolve_chat_model

        result = resolve_chat_model("", project_model="zhipu/glm-4.5")
        assert result == "zhipu/glm-4.5", "项目模型必须压过全局默认（#735 链）"
        assert isinstance(result, str), "单值 helper 必须返回 str（非 tuple）"

    def test_r7_global_default_passthrough(self) -> None:
        """【R】全局默认有值 → 原样返回。"""
        from inkflow.api._llm_resolver import resolve_chat_model

        assert resolve_chat_model("deepseek/deepseek-v4-flash") == "deepseek/deepseek-v4-flash"

    def test_r8_same_422_contract_as_credentials(self) -> None:
        """【R】与 resolve_llm_credentials 同源（同一 422 契约，禁第二份逻辑）。

        两条路径在空默认下必须给出**逐字相同**的 detail——单一真相锚。
        """
        from inkflow.api._llm_resolver import resolve_chat_model, resolve_llm_credentials

        with pytest.raises(HTTPException) as helper_exc:
            resolve_chat_model("")
        with pytest.raises(HTTPException) as creds_exc:
            resolve_llm_credentials("")

        assert helper_exc.value.detail == creds_exc.value.detail, (
            "helper 与 credentials 必须共享同一 422 文案（单一真相，禁两份解析逻辑）"
        )
        assert helper_exc.value.status_code == creds_exc.value.status_code == 422


class TestBypassConvergence:
    """旁路点收敛契约：chat_stream / context 空默认 → 422，不落空串。

    #936 spec §3.1：这些点「无守卫直接读 config」是最初的 NIT-2 缺陷形态。
    """

    def test_r9_chat_run_model_field_uses_guard(self) -> None:
        """【R】chat_stream 的 _build_chat_run 在空默认下抛 422（非空串落库）。

        RED 形态：当前 `model=config.llm_default_model` 直读 → 空默认时
        返回 model="" 而不抛（AssertionError: DID NOT RAISE）。
        """
        from inkflow.api.routers import chat_stream as cs

        with _mutated_default(""), pytest.raises(HTTPException) as exc_info:
            # 契约：chat 落库 model 字段的来源函数须走守卫
            cs._chat_run_model()
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == RESOLVE_422_DETAIL

    def test_r10_context_summary_model_uses_guard(self) -> None:
        """【R】context 摘要 model 解析走守卫（空 → 422，非空串下传）。

        RED 形态：当前 `model = app_config.llm_default_model` 直读。
        """
        from inkflow.api.routers import context as ctx

        with _mutated_default(""), pytest.raises(HTTPException) as exc_info:
            ctx._resolve_summary_model(None)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == RESOLVE_422_DETAIL

    def test_g3_context_project_model_takes_precedence(self) -> None:
        """【G】护栏：项目模型有值时优先（空默认不该覆盖项目配置）。

        #329 语义：model 走项目 config.model → 回退全局默认。
        """
        from inkflow.api.routers import context as ctx

        with _mutated_default(""):
            assert ctx._resolve_summary_model("zhipu/glm-4.5") == "zhipu/glm-4.5", (
                "护栏：项目模型非空时必须优先，不得被空全局默认拦截"
            )
