"""#1319 上下文注入面板勾选生效（agent 轨 override 打通）契约。

背景（父侧实测，与 issue 正文假设不同）：
GUI 写作「生成/续写」实际走 `usePipeline` → `POST /api/v1/agent/pipelines/stream`
→ `AgentService.stream_pipeline/execute`，**不经过** `WritingRequest` /
`WritingService`。该轨的设定注入由 `_assemble_setting_context`（agent_service.py:771）
自行从 character_repo / world_repo / outline_repo **全量**拉取（limit=50）拼成
`variables["setting"]` 文本 —— 这是「上下文注入」面板勾选对生成无影响的真因。

修复面 = 让 `PipelineExecuteRequest.override`（复用既有 `ContextOverride` 三态语义）
透传至 `_assemble_setting_context`，按 id 白名单过滤三源。

契约（父侧定稿）：
- `PipelineExecuteRequest` 新增 `override: ContextOverride | None = None`
  （缺省 None = 全注入，既有行为逐字不变）
- `_assemble_setting_context(project_id, variables, override=None)` 新增带默认值的
  关键字参数 → 既有调用点零改动
- override 三态（镜像 `context_service._apply_override` #1235 语义）：
  - `None`              → 全注入（默认）
  - `character_ids=[]`  → 该源不产出条目（显式空 = 删空）
  - `character_ids=[x]` → 仅注入 id 命中 x 的角色
  - 未覆盖的源（本次仅 character/world 有 id 面；outline 无 override 面）→ 原样全注入
- `world_ids` 同理作用于 world_setting
- **outline 不参与过滤**（`ContextOverride` 无 outline 字段，与 #1319 issue
  「三类不可过滤」自列一致）

RED 预期（本文件首轮应 FAIL）：
- test_override_character_whitelist_filters_setting: FAILED
  （override 字段不存在 / 过滤未实现 → TypeError 或 setting 含不该出现的角色）
- test_override_world_whitelist_filters_setting: FAILED
- test_override_empty_list_removes_source: FAILED
- test_override_passthrough_via_execute: FAILED
守护用例（RED 阶段即 PASS，GREEN 后锁行为）：
- test_default_none_injects_all（既有行为回归锁）
- test_outline_not_filtered_by_override
- test_override_survives_single_source_failure

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.character import Character
from inkflow.domain.models.context import ContextOverride
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService

pytestmark = pytest.mark.asyncio

# ── 辅助工厂（镜像 test_agent_service_setting.py 形态，自包含避免跨文件耦合）──


def _make_project(project_id: uuid.UUID | None = None) -> Project:
    return Project(
        id=project_id or uuid.uuid4(),
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_character(project_id: uuid.UUID, name: str) -> Character:
    return Character(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        personality=f"{name}的性格",
        background="",
        goals="",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_world(project_id: uuid.UUID, name: str) -> WorldSetting:
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="设定",
        content=f"{name}的内容",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_outline(project_id: uuid.UUID, name: str) -> Outline:
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=f"{name}的描述",
        level="overall",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class MockPipeline:
    def __init__(self) -> None:
        self.result = PipelineResult(
            stages=[StageResult(stage_id="writer", status=StageStatus.COMPLETED, output="正文")],
            final_output="正文",
            status=StageStatus.COMPLETED,
            total_duration_ms=1,
        )
        self.executed_context: PipelineContext | None = None

    async def execute(
        self,
        stages: list[PipelineStage],
        context: PipelineContext,
        conditional_edges: list[tuple[str, str]] | None = None,
    ) -> PipelineResult:
        self.executed_context = context
        return self.result

    def validate(self, stages: list[PipelineStage]) -> list[str]:
        return []


class FakeExecution:
    def __init__(self, pipeline: str, project_id: str, chapter_id: str | None = None) -> None:
        self.id = str(uuid.uuid4())
        self.pipeline = pipeline
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.status = "pending"
        self.stages: list[dict] = []
        self.final_output = ""
        self.error = ""
        self.total_duration_ms = 0
        self.created_at = datetime.now(UTC)


class MockExecutionStore:
    def __init__(self) -> None:
        self.executions: dict[str, FakeExecution] = {}

    async def create_execution(
        self, pipeline: str, project_id: str, chapter_id: str | None = None
    ) -> FakeExecution:
        execution = FakeExecution(pipeline, project_id, chapter_id)
        self.executions[execution.id] = execution
        return execution

    async def get_execution(self, execution_id: str) -> FakeExecution | None:
        return self.executions.get(execution_id)

    async def update_status(self, execution_id: str, status: str, **kwargs: object) -> None:
        if execution_id in self.executions:
            self.executions[execution_id].status = status

    async def update_stages(self, execution_id: str, stages: list, status: str, **kwargs: object):
        execution = self.executions.get(execution_id)
        if execution is not None:
            execution.stages = stages
            execution.status = status


class MockProjectRepo:
    def __init__(self, project: Project | None) -> None:
        self.project = project

    async def get(self, project_id: object) -> Project | None:
        return self.project


class MockCharacterRepo:
    def __init__(self, characters: list[Character]) -> None:
        self.characters = characters

    async def list(self, project_id: object, *args: object, **kwargs: object):
        return self.characters, len(self.characters)


class MockWorldRepo:
    def __init__(self, settings: list[WorldSetting]) -> None:
        self.settings = settings

    async def list(self, project_id: object, *args: object, **kwargs: object):
        return self.settings, len(self.settings)


class MockOutlineRepo:
    def __init__(self, outlines: list[Outline]) -> None:
        self.outlines = outlines

    async def list(self, project_id: object, *args: object, **kwargs: object):
        return self.outlines, len(self.outlines)


def _build_service(project: Project, *, world_fail: Exception | None = None):
    pipeline = MockPipeline()
    store = MockExecutionStore()
    service = AgentService(
        pipeline=pipeline,  # type: ignore[arg-type]  # MockPipeline 鸭子类型满足协议
        db_session=None,
        store=store,
        project_repo=MockProjectRepo(project),
    )
    return service, pipeline, store


async def _run_and_get_setting(service, pipeline, request) -> str:
    """执行 request 并返回后台任务落定后的 variables['setting']（缺键返回 ''）。"""
    await service.execute(request)
    await asyncio.sleep(0.05)  # 等待 fire-and-forget 后台任务
    assert pipeline.executed_context is not None
    return pipeline.executed_context.variables.get("setting", "")


# ── 契约用例 ────────────────────────────────────────────────────


class TestOverrideCharacterWhitelist:
    async def test_override_character_whitelist_filters_setting(self):
        """override.character_ids=[甲的 id] → setting 只含甲，不含乙。

        RED 预期：FAILED（override 字段未透传 → 两个角色都进 setting）。
        """
        project = _make_project()
        char_a = _make_character(project.id, "角色甲")
        char_b = _make_character(project.id, "角色乙")
        service, pipeline, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([char_a, char_b])
        service._world_repo = MockWorldRepo([])
        service._outline_repo = MockOutlineRepo([])

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(character_ids=[char_a.id]),
        )
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "角色甲" in setting
        assert "角色乙" not in setting, "白名单外的角色不得注入"

    async def test_override_empty_list_removes_source(self):
        """override.character_ids=[] → 显式空 = 删空，角色源零产出（#1235 语义）。

        RED 预期：FAILED（同上，未过滤）。
        """
        project = _make_project()
        service, pipeline, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([_make_character(project.id, "角色甲")])
        service._world_repo = MockWorldRepo([_make_world(project.id, "天玄大陆")])
        service._outline_repo = MockOutlineRepo([])

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(character_ids=[]),
        )
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "角色甲" not in setting, "显式空列表 = 该源删空"
        assert "天玄大陆" in setting, "未覆盖的源仍全注入"


class TestOverrideWorldWhitelist:
    async def test_override_world_whitelist_filters_setting(self):
        """override.world_ids=[甲] → setting 只含该世界观条目。

        RED 预期：FAILED。
        """
        project = _make_project()
        world_a = _make_world(project.id, "世界观甲")
        world_b = _make_world(project.id, "世界观乙")
        service, pipeline, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([])
        service._world_repo = MockWorldRepo([world_a, world_b])
        service._outline_repo = MockOutlineRepo([])

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(world_ids=[world_a.id]),
        )
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "世界观甲" in setting
        assert "世界观乙" not in setting, "白名单外的世界观条目不得注入"

    async def test_outline_not_filtered_by_override(self):
        """override 不覆盖 outline（ContextOverride 无 outline 字段）→ 大纲仍全注入。

        守护用例：RED 阶段即 PASS（当前全注入），GREEN 后锁「不得顺手把 outline 也过滤掉」。
        """
        project = _make_project()
        service, pipeline, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([_make_character(project.id, "角色甲")])
        service._world_repo = MockWorldRepo([_make_world(project.id, "世界观甲")])
        service._outline_repo = MockOutlineRepo([_make_outline(project.id, "主线大纲")])

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(character_ids=[]),
        )
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "主线大纲" in setting, "outline 无 override 面，应保持全注入"


class TestOverrideDefaultAndGuards:
    async def test_default_none_injects_all(self):
        """不传 override（None）→ 三源全注入，既有行为逐字不变。

        守护用例：RED 阶段即 PASS（当前行为），GREEN 后锁向后兼容。
        """
        project = _make_project()
        service, pipeline, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([_make_character(project.id, "角色甲")])
        service._world_repo = MockWorldRepo([_make_world(project.id, "世界观甲")])
        service._outline_repo = MockOutlineRepo([_make_outline(project.id, "主线大纲")])

        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_auto")
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "角色甲" in setting
        assert "世界观甲" in setting
        assert "主线大纲" in setting

    async def test_override_survives_single_source_failure(self):
        """世界源抛异常 + 角色白名单 → 世界源跳过（既有隔离语义），角色白名单仍生效。

        守护用例 + 过滤路径交叉：RED 阶段 FAILED（白名单未生效）。
        """
        project = _make_project()
        char_a = _make_character(project.id, "角色甲")
        char_b = _make_character(project.id, "角色乙")
        service, pipeline, _ = _build_service(project)

        class _FailingWorldRepo:
            async def list(self, project_id: object, *args: object, **kwargs: object):
                raise RuntimeError("世界观读取失败")

        service._character_repo = MockCharacterRepo([char_a, char_b])
        service._world_repo = _FailingWorldRepo()
        service._outline_repo = MockOutlineRepo([])

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(character_ids=[char_a.id]),
        )
        setting = await _run_and_get_setting(service, pipeline, request)

        assert "角色甲" in setting
        assert "角色乙" not in setting

    async def test_override_passthrough_via_stream(self):
        """stream_pipeline 路径同样透传 override → _assemble_setting_context 收到。

        契约锚：override 必须在 stream 与 execute 两条入口都生效
        （GUI 走 /agent/pipelines/stream，即 stream 路径）。
        """
        project = _make_project()
        char_a = _make_character(project.id, "角色甲")
        char_b = _make_character(project.id, "角色乙")
        service, _, _ = _build_service(project)
        service._character_repo = MockCharacterRepo([char_a, char_b])
        service._world_repo = MockWorldRepo([])
        service._outline_repo = MockOutlineRepo([])

        captured: dict[str, object] = {}

        async def _spy(project_id, variables, override=None, injected=None):
            captured["override"] = override
            return variables

        service._assemble_setting_context = _spy  # type: ignore[method-assign]  # 探针替换

        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            override=ContextOverride(character_ids=[char_a.id]),
        )
        try:
            async for _ in service.stream_pipeline(request):
                pass
        except Exception:
            pass  # 管线 mock 非流式 → 降级路径异常可忽略，只验 override 已到达

        assert captured.get("override") is not None, "stream 路径必须把 override 传到装配层"
        assert captured["override"].character_ids == [char_a.id]
