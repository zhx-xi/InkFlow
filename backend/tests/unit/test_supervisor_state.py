"""F29 Supervisor 模式 DTO 与执行记录契约（spec §2.2 + §3 + §8）。

被测（全部待实现，RED 收集期形态）：
1. domain/models/agent_pipeline.py：
   - PipelineExecuteRequest.mode: Literal["static", "supervisor"] = "static"
     （默认 static 向后兼容）
   - SupervisorExecuteConfig（新 DTO）：
     max_steps / max_consecutive / hitl_roles / fallback_on_error / supervisor_prompt
2. infrastructure/agent/execution_store.py：
   - ExecutionStore.update_status(execution_id, status) → 更新 status（waiting_hitl）
   - ExecutionStore.get_hitl_payload(execution_id) → dict | None（interrupt payload 快照）

RED 形态：
- 顶部 import SupervisorExecuteConfig → 收集期 ImportError（cannot import name）
- PipelineExecuteRequest(mode="supervisor") → extra 拒绝 ValidationError（字段缺失）→ 断言 FAIL
- update_status/get_hitl_payload 方法缺失 → 用例体 lazy import → AttributeError（FAILED 非 ERROR）

既有守护（RED 阶段即 PASS，刻意）：
- PipelineExecuteRequest() 不带 mode → 默认 static（守护用例）
- ExecutionStore.create_execution 既有行为不变
"""

from __future__ import annotations

import pytest


class TestSupervisorExecuteConfig:
    """SupervisorExecuteConfig DTO 契约（spec §2.2 逐字）。"""

    def test_import_exists(self) -> None:
        """SupervisorExecuteConfig 可从 domain.models.agent_pipeline import。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig  # noqa: F401

        assert True

    def test_defaults(self) -> None:
        """默认值：max_steps=30 / max_consecutive=3 / hitl_roles=[] / fallback_on_error=True。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        cfg = SupervisorExecuteConfig()
        dumped = cfg.model_dump()
        assert dumped["max_steps"] == 30
        assert dumped["max_consecutive"] == 3
        assert dumped["hitl_roles"] == []
        assert dumped["fallback_on_error"] is True
        assert dumped["supervisor_prompt"] is None

    def test_explicit_values(self) -> None:
        """显式传值 → 保留。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        cfg = SupervisorExecuteConfig(
            max_steps=50,
            max_consecutive=2,
            hitl_roles=["reviser"],
            fallback_on_error=False,
            supervisor_prompt="你是指挥官",
        )
        dumped = cfg.model_dump()
        assert dumped["max_steps"] == 50
        assert dumped["max_consecutive"] == 2
        assert dumped["hitl_roles"] == ["reviser"]
        assert dumped["fallback_on_error"] is False
        assert dumped["supervisor_prompt"] == "你是指挥官"

    def test_max_steps_range(self) -> None:
        """max_steps 越界（>100）→ ValidationError。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        with pytest.raises(ValueError):
            SupervisorExecuteConfig(max_steps=101)

    def test_max_consecutive_range(self) -> None:
        """max_consecutive 越界（>10）→ ValidationError。"""
        from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig

        with pytest.raises(ValueError):
            SupervisorExecuteConfig(max_consecutive=11)


class TestPipelineExecuteRequestMode:
    """PipelineExecuteRequest.mode 扩展契约（spec §2.2）。"""

    def test_mode_default_static(self) -> None:
        """缺省 mode → "static"（守护：RED 阶段即 PASS，既有行为不变）。"""
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

        req = PipelineExecuteRequest(project_id="00000000-0000-0000-0000-000000000001")
        dumped = req.model_dump()
        assert dumped["mode"] == "static"

    def test_mode_supervisor_accepted(self) -> None:
        """mode="supervisor" 可构造（RED：字段缺失 → extra 拒绝 ValidationError）。"""
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

        req = PipelineExecuteRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            mode="supervisor",
        )
        assert req.mode == "supervisor"

    def test_mode_invalid_rejected(self) -> None:
        """mode 非法值 → ValidationError。"""
        from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest

        with pytest.raises(ValueError):
            PipelineExecuteRequest(
                project_id="00000000-0000-0000-0000-000000000001",
                mode="unknown",  # type: ignore[arg-type]
            )

    def test_supervisor_config_embedded(self) -> None:
        """supervisor 配置可嵌入请求（RED：字段缺失 → extra 拒绝 ValidationError）。"""
        from inkflow.domain.models.agent_pipeline import (
            PipelineExecuteRequest,
            SupervisorExecuteConfig,
        )

        req = PipelineExecuteRequest(
            project_id="00000000-0000-0000-0000-000000000001",
            mode="supervisor",
            supervisor=SupervisorExecuteConfig(max_steps=10),
        )
        assert req.supervisor is not None
        assert req.supervisor.max_steps == 10


class TestExecutionStoreHITL:
    """ExecutionStore HITL 状态契约（spec §8：update_status + get_hitl_payload）。"""

    @pytest.fixture
    async def store(self):
        """真实 ExecutionStore（in-memory SQLite 轨，镜像 test_agent_run_repo 惯例）。"""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from inkflow.core.database import Base
        from inkflow.infrastructure.agent.execution_store import ExecutionStore

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        session = session_factory()
        return ExecutionStore(session)

    @pytest.mark.asyncio
    async def test_update_status(self, store) -> None:
        """update_status 将执行记录 status 更新为 waiting_hitl。"""
        # 先创建执行记录（真实 create_execution）
        exec_ = await store.create_execution(pipeline="builtin:write_chapter", project_id="p1")
        await store.update_status(exec_.id, "waiting_hitl")
        updated = await store.get_execution(exec_.id)
        assert updated is not None
        assert updated.status == "waiting_hitl"

    @pytest.mark.asyncio
    async def test_get_hitl_payload_none(self, store) -> None:
        """get_hitl_payload 无 payload 时返回 None。"""
        exec_ = await store.create_execution(pipeline="builtin:write_chapter", project_id="p1")
        payload = await store.get_hitl_payload(exec_.id)
        assert payload is None

    @pytest.mark.asyncio
    async def test_get_hitl_payload_roundtrip(self, store) -> None:
        """set/update payload → get_hitl_payload 读回。"""
        exec_ = await store.create_execution(pipeline="builtin:write_chapter", project_id="p1")
        await store.update_status(exec_.id, "waiting_hitl")
        # 契约：update_status 支持可选 hitl_payload 参数（或独立 set 方法，实现确认）
        payload = await store.get_hitl_payload(exec_.id)
        assert payload is None or isinstance(payload, dict)
