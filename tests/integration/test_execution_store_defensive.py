"""ExecutionStore 防御分支集成测试（F44 阶段4 覆盖率门禁补测）。

覆盖 src/inkflow/infrastructure/agent/execution_store.py 的 None 防御分支：
- update_stages 对不存在 execution_id → 提前返回（L67-69）
- update_status 对不存在 execution_id → 提前返回（L86-88）
- update_status 带 hitl_payload 非 None → 落库读回（L90-91）
- get_hitl_payload 对不存在 execution_id → None（L96-98）

fixture 镜像 tests/conftest.py 的 db_session（function-scoped in-memory SQLite，
Base.metadata.create_all 自动建表）。
"""

import uuid

import pytest

from inkflow.infrastructure.agent import ExecutionStore


@pytest.mark.asyncio
class TestExecutionStoreDefensive:
    async def test_update_stages_missing_execution_noop(self, db_session):
        """update_stages 对不存在的 execution_id → 不抛错、无副作用（L67-69）。"""
        store = ExecutionStore(db_session)
        execution_id = str(uuid.uuid4())

        await store.update_stages(
            execution_id,
            [{"stage_id": "outline", "status": "completed", "output": "大纲"}],
            "completed",
            final_output="章节正文",
        )

        assert await store.get_execution(execution_id) is None  # 无记录被创建
        _, total = await store.list_executions(project_id=str(uuid.uuid4()))
        assert total == 0  # 表无任何副作用残留

    async def test_update_status_missing_execution_noop(self, db_session):
        """update_status 对不存在的 execution_id → 不抛错（L86-88）。"""
        store = ExecutionStore(db_session)
        execution_id = str(uuid.uuid4())

        await store.update_status(
            execution_id, "waiting_hitl", {"question": "确认继续下一卷？"}
        )

        assert await store.get_execution(execution_id) is None

    async def test_update_status_persists_hitl_payload(self, db_session):
        """update_status 带 hitl_payload 非 None → 落库读回（L90-91）。"""
        store = ExecutionStore(db_session)
        execution = await store.create_execution(
            pipeline="book:volume", project_id=str(uuid.uuid4())
        )
        payload = {
            "question": "确认继续下一卷？",
            "volume_index": 1,
            "total_volumes": 2,
        }

        await store.update_status(execution.id, "waiting_hitl", payload)

        loaded = await store.get_hitl_payload(execution.id)
        assert loaded == payload
        assert (await store.get_execution(execution.id)).status == "waiting_hitl"

    async def test_get_hitl_payload_missing_execution_returns_none(self, db_session):
        """get_hitl_payload 对不存在 execution_id → None（L96-98）。"""
        store = ExecutionStore(db_session)

        assert await store.get_hitl_payload(str(uuid.uuid4())) is None

    async def test_update_status_without_payload_keeps_existing(self, db_session):
        """update_status 不带 hitl_payload（None）→ 状态更新、既有 payload 保留
        （覆盖 L90 if 的 False 分支 90->92）。"""
        store = ExecutionStore(db_session)
        execution = await store.create_execution(
            pipeline="book:volume", project_id=str(uuid.uuid4())
        )
        payload = {"question": "确认继续下一卷？"}
        await store.update_status(execution.id, "waiting_hitl", payload)

        await store.update_status(execution.id, "completed")

        loaded = await store.get_execution(execution.id)
        assert loaded.status == "completed"
        assert loaded.hitl_payload == payload  # 未覆盖
