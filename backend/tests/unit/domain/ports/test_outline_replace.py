"""#669 AI 生成覆盖当前大纲（替换语义，用户确认后覆盖）— A 轨 RED 契约测试.

覆盖 contract-669 §8「A 轨」A1-A14 全部用例:
- 领域模型校验（OutlineGenerateRequest mode/target_outline_id 交叉校验、
  OutlineGenerationResult 新字段默认值）;
- OutlineService + OutlineGenerator 组合行为契约（真实 service + 真实
  generator，mock 边界在 LLM/模板/仓储）: replace 暂存零写入 / 前置校验 /
  confirm_replace 两态（应用/取消）/ 快照可恢复 / 幂等 / save=false 纯预览 /
  new 默认路径守护 / 围栏输出解析守护。

【R】= 必红（目标行为未实现）;【G】= 守护（RED 期即绿，GREEN 后不得回归）。
RED 期契约符号（mode/target_outline_id/requires_confirmation 字段、
OutlineReplaceError/OutlineTargetProjectError 异常、confirm_replace 方法）
尚不存在——未实现符号一律函数体内 import 或 getattr 兜底，绝不顶层 import
（避免整个文件 collection error）。

依据: .hermes/plans/contract-669.md §1/§4/§8（唯一权威）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    PlotPoint,
    StoryArc,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.outline_errors import OutlineNotFoundError, OutlineServiceError
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services.outline_service import OutlineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_OTHER = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TARGET_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000010")  # 覆盖目标大纲 id
OLD1 = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000011")  # 旧情节点 1
OLD2 = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000012")  # 旧情节点 2
ARC_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000013")  # 既有弧线（按名复用）
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _outline(
    name: str,
    *,
    outline_id: uuid.UUID | None = None,
    project_id: uuid.UUID = PID,
    description: str = "",
    extra: dict | None = None,
) -> Outline:
    """构造测试用大纲实体（固定时间戳）。"""
    return Outline(
        id=outline_id or uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        extra=extra or {},
        created_at=TS,
        updated_at=TS,
    )


def _arc(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    arc_id: uuid.UUID | None = None,
) -> StoryArc:
    """构造测试用故事弧线实体。"""
    return StoryArc(
        id=arc_id or uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """项目存在校验用实体（generate 入口）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(model=DEFAULT_MODEL),
        created_at=TS,
        updated_at=TS,
    )


def _payload(
    outline: dict | None = None,
    arcs: list[dict] | None = None,
    plot_points: list[dict] | None = None,
) -> str:
    """构造合法生成 JSON 输出（outline/arcs/plot_points 三层，§5.2 模板格式）。"""
    return json.dumps(
        {
            "outline": outline
            if outline is not None
            else {"name": "雾都谜案大纲", "description": "侦探小说总体设计"},
            "arcs": arcs or [],
            "plot_points": plot_points or [],
        },
        ensure_ascii=False,
    )


def _ok_response(payload: str) -> ChatResponse:
    return ChatResponse(content=payload, model=DEFAULT_MODEL)


def _staged_outline() -> tuple[Outline, PlotPoint, PlotPoint]:
    """目标大纲（extra 预置 replace_pending：2 新情节点 + 1 弧线名）+ 2 旧情节点。

    pending 结构逐字对齐契约 §2: generated=GeneratedOutline.model_dump(mode="json")、
    model、staged_at。
    """
    generated = GeneratedOutline(
        name="雾都谜案大纲",
        description="覆盖后整体设计",
        arcs=[GeneratedArc(name="主线", description="追查真凶")],
        plot_points=[
            GeneratedPlotPoint(name="新开局", type="开篇", description="新开局描述", arc="主线"),
            GeneratedPlotPoint(name="新收束", type="结局", description="新收束描述", arc="主线"),
        ],
    )
    outline = _outline(
        "雾都谜案大纲",
        outline_id=TARGET_ID,
        extra={
            "replace_pending": {
                "generated": generated.model_dump(mode="json"),
                "model": DEFAULT_MODEL,
                "staged_at": "2026-08-02T00:00:00+00:00",
            }
        },
    )
    old1 = PlotPoint(
        id=OLD1,
        outline_id=TARGET_ID,
        project_id=PID,
        name="旧点一",
        type="开篇",
        description="旧描述一",
        position=1,
        created_at=TS,
        updated_at=TS,
    )
    old2 = PlotPoint(
        id=OLD2,
        outline_id=TARGET_ID,
        project_id=PID,
        name="旧点二",
        type="发展",
        description="旧描述二",
        position=2,
        created_at=TS,
        updated_at=TS,
    )
    return outline, old1, old2


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    """Mock PromptManager — 渲染结果模拟 str.replace 透传 Jinja2 条件段。"""
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name="outline_generate",
        description="Outline generation template",
        system_prompt=(
            "你是小说大纲规划师。输出严格 JSON。\n"
            "{% if num_chapters %}"
            "请将情节点数量控制在约 {{ num_chapters }} 个。"
            "{% endif %}"
        ),
        human_prompt="项目信息：\n{project_info}\n\n创作约束：\n{prompt}",
        variables=["project_info", "prompt", "num_chapters"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是小说大纲规划师。输出严格 JSON。\n"
                        "{% if num_chapters %}"
                        "请将情节点数量控制在约 {{ num_chapters }} 个。"
                        "{% endif %}"
                    ),
                },
                {
                    "role": "user",
                    "content": "项目信息：\n项目名：测试项目\n\n创作约束：\n",
                },
            ],
            token_estimate=80,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — service + generator 共用同一实例。"""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.update = AsyncMock(side_effect=lambda o: o)
    repo.hard_delete_point = AsyncMock(return_value=True)
    repo.list_points = AsyncMock(return_value=[])
    repo.get_arc_by_name = AsyncMock(return_value=None)
    repo.add_arc = AsyncMock(side_effect=lambda a: a)
    repo.add_point = AsyncMock(side_effect=lambda p: p)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — generate 入口校验项目存在性。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def generator(mock_llm, mock_prompt_manager, mock_repo) -> OutlineGenerator:
    """真实 OutlineGenerator，注入 mock LLM/模板/仓储。"""
    return OutlineGenerator(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_repo,
    )


@pytest.fixture
def service(generator, mock_repo, mock_project_repo) -> OutlineService:
    """真实 OutlineService + 真实 OutlineGenerator 组合（仓储共用同一 mock）。"""
    return OutlineService(
        repository=mock_repo,
        generator=generator,
        project_repo=mock_project_repo,
    )


class TestOutlineGenerateRequestReplaceValidation:
    """§1.1 OutlineGenerateRequest 新增 mode/target_outline_id 校验（逐字文案）。"""

    def test_a1_replace_mode_cross_field_validation_red(self) -> None:
        """A1【R】mode 交叉校验：
        replace 缺 target_outline_id → 「覆盖模式必须指定目标大纲」;
        mode 非法 → 「生成模式只能为 new/replace」;
        new 带 target_outline_id = #668 追加合法态（rebase 拍板：字段双模共享，
        不校验——原「目标大纲仅在覆盖模式下有效」条款撤销）。
        （RED 期字段不存在，pydantic 忽略未知字段 → 前两条均 DID NOT RAISE。）"""
        with pytest.raises(ValidationError, match="覆盖模式必须指定目标大纲"):
            OutlineGenerateRequest(project_id=PID, mode="replace")
        with pytest.raises(ValidationError, match="生成模式只能为 new/replace"):
            OutlineGenerateRequest(project_id=PID, mode="append")
        # 追加语义合法（#911 已合入）：new + target 不抛
        ok = OutlineGenerateRequest(project_id=PID, target_outline_id=TARGET_ID)
        assert ok.mode == "new"
        assert ok.target_outline_id == TARGET_ID

    def test_a2_dto_defaults_backward_compatible_guard(self) -> None:
        """A2【G】默认值向后兼容护栏：request 默认 mode=="new" 且 target_outline_id
        is None；result 默认 requires_confirmation is False 且 target_outline_id is
        None——既有构造（不带新字段）不破坏，GREEN 后默认值语义即现行为。

        偏离说明：RED 期字段尚未实现，字段默认值断言以 getattr(实例, 字段,
        契约默认值) 兜底形态落地——RED 期取兜底值（= 契约默认）通过，GREEN 后
        字段存在取真值，护栏语义不变。直接属性访问在 RED 期 AttributeError
        会误伤【G】分类（契约要求 G 全 PASS）。
        """
        req = OutlineGenerateRequest(project_id=PID)
        assert getattr(req, "mode", "new") == "new"
        assert getattr(req, "target_outline_id", None) is None
        res = OutlineGenerationResult(saved=True, model=DEFAULT_MODEL)
        assert getattr(res, "requires_confirmation", False) is False
        assert getattr(res, "target_outline_id", None) is None
        # 既有必填字段契约不被新字段破坏
        assert req.project_id == PID
        assert res.saved is True
        assert res.model == DEFAULT_MODEL


class TestGenerateReplaceMode:
    """§4.1/§4.2 replace 模式：暂存 / 前置校验 / save=false / new 默认路径。"""

    async def test_a3_replace_mode_stages_pending_without_writes(
        self, service, mock_llm, mock_repo
    ) -> None:
        """A3【R】generate replace 暂存：saved=False、requires_confirmation=True、
        preview 非空、target_outline_id 回显目标；repo.add/add_point/add_arc/
        hard_delete_point 均 not awaited（确认前零破坏）；repo.update awaited 一次
        且实参 extra["replace_pending"] 含生成情节点与 staged_at/model 键。
        （RED 期无 mode 分派 → 走新建老流程 saved=True，首个断言即 FAIL。）"""
        mock_repo.get = AsyncMock(return_value=_outline("被覆盖大纲", outline_id=TARGET_ID))
        mock_llm.chat.return_value = _ok_response(
            _payload(
                outline={"name": "覆盖版大纲", "description": "生成后覆盖当前大纲"},
                arcs=[{"name": "主线", "description": "追查真凶"}],
                plot_points=[
                    {
                        "name": "新开局",
                        "type": "开篇",
                        "description": "替代旧点一",
                        "arc": "主线",
                    }
                ],
            )
        )
        result = await service.generate(
            OutlineGenerateRequest(project_id=PID, mode="replace", target_outline_id=TARGET_ID)
        )
        assert result.saved is False
        assert result.requires_confirmation is True
        assert result.preview is not None
        assert result.target_outline_id == TARGET_ID
        mock_repo.add.assert_not_awaited()
        mock_repo.add_point.assert_not_awaited()
        mock_repo.add_arc.assert_not_awaited()
        mock_repo.hard_delete_point.assert_not_awaited()
        mock_repo.update.assert_awaited_once()
        updated = mock_repo.update.await_args.args[0]
        assert isinstance(updated, Outline)
        pending = updated.extra["replace_pending"]
        assert [p["name"] for p in pending["generated"]["plot_points"]] == ["新开局"]
        assert pending["model"] == DEFAULT_MODEL
        assert "staged_at" in pending

    async def test_a4_replace_target_missing_raises_before_llm(
        self, service, mock_llm, mock_repo
    ) -> None:
        """A4【R】replace 且目标大纲不存在（repo.get→None）→ OutlineNotFoundError；
        llm.chat not awaited（LLM 前拦截，省 token 快速失败）。
        （RED 期无前置校验 → 不抛错，pytest.raises DID NOT RAISE。）"""
        mock_repo.get = AsyncMock(return_value=None)
        mock_llm.chat.return_value = _ok_response(_payload())
        request = OutlineGenerateRequest(
            project_id=PID, mode="replace", target_outline_id=TARGET_ID
        )
        with pytest.raises(OutlineNotFoundError):
            await service.generate(request)
        mock_llm.chat.assert_not_awaited()

    async def test_a5_replace_cross_project_target_raises_before_llm(
        self, service, mock_llm, mock_repo
    ) -> None:
        """A5【R】replace 且目标大纲跨项目 → OutlineTargetProjectError（422 语义）；
        llm.chat not awaited。
        （OutlineTargetProjectError 为契约新增异常，RED 期不存在 → 函数体内
        import 即 ImportError FAIL，形态=符号未实现。）"""
        from inkflow.domain.ports.outline_errors import OutlineTargetProjectError

        foreign = _outline("别家项目大纲", project_id=PID_OTHER)
        mock_repo.get = AsyncMock(return_value=foreign)
        mock_llm.chat.return_value = _ok_response(_payload())
        request = OutlineGenerateRequest(
            project_id=PID, mode="replace", target_outline_id=TARGET_ID
        )
        with pytest.raises(OutlineTargetProjectError):
            await service.generate(request)
        mock_llm.chat.assert_not_awaited()

    async def test_a10_generate_new_default_path_unchanged_guard(
        self, service, mock_llm, mock_repo
    ) -> None:
        """A10【G】mode 默认 new 路径守护：请求不带 mode（RED 期无该字段=默认
        形态；GREEN 后默认 "new"）→ 全走新建老流程——repo.add awaited 一次、
        落库实体 extra 无 replace_pending、repo.update not awaited（默认路径
        不被替换逻辑劫持）。镜像 test_outline_generation.py 既有 fixture 形态。
        """
        mock_llm.chat.return_value = _ok_response(
            _payload(
                outline={"name": "雾都谜案新纲", "description": "整体设计"},
                arcs=[{"name": "主线"}],
                plot_points=[{"name": "开篇命案", "arc": "主线"}],
            )
        )
        result = await service.generate(OutlineGenerateRequest(project_id=PID))
        assert result.saved is True
        assert result.outline is not None
        assert result.outline.name == "雾都谜案新纲"
        assert result.outline.extra.get("replace_pending") is None
        assert mock_repo.add.await_count == 1
        assert mock_repo.add_point.await_count == 1
        mock_repo.update.assert_not_awaited()

    async def test_a11_replace_save_false_pure_preview(self, service, mock_llm, mock_repo) -> None:
        """A11【R】replace + save=False → 纯预览零写入：saved=False、preview 非空、
        requires_confirmation is False、repo.update not awaited（连 pending 都不写）。
        （RED 期 requires_confirmation 字段缺失 → AttributeError FAIL=字段不存在；
        GREEN 后 save=False 分支任何 mode 均不写 pending。）"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                outline={"name": "预览覆盖大纲"},
                plot_points=[{"name": "预览点", "type": "开篇"}],
            )
        )
        result = await service.generate(
            OutlineGenerateRequest(
                project_id=PID,
                save=False,
                mode="replace",
                target_outline_id=TARGET_ID,
            )
        )
        assert result.saved is False
        assert result.preview is not None
        assert result.requires_confirmation is False
        mock_repo.update.assert_not_awaited()
        mock_repo.add.assert_not_awaited()
        mock_repo.add_point.assert_not_awaited()

    async def test_a14_generate_fenced_output_reuses_robust_parser_guard(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """A14【G】LLM 围栏输出（```json ...```）→ 正常解析落库（现有
        _extract_json_fragment 覆盖，守护替换管线复用同一健壮解析 ②-⑤）。

        偏离说明：RED 期 mode 字段不存在，无法显式 mode="replace" 触发暂存
        ——以默认 new 路径守护共享解析层；GREEN 后请求默认 mode="new"，
        本用例继续守护（替换暂存路径本身由 A3/A11 行为契约覆盖）。
        """
        payload = _payload(
            arcs=[{"name": "主线"}],
            plot_points=[{"name": "开篇命案", "type": "开篇", "arc": "主线"}],
        )
        fenced = f"好的，以下是生成的大纲：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：测试项目",
            default_model=DEFAULT_MODEL,
        )
        assert result.saved is True
        assert [p.name for p in result.plot_points] == ["开篇命案"]
        assert mock_repo.add_point.await_count == 1


class TestConfirmReplace:
    """§4.2 confirm_replace 两段式确认：应用（approved=True）/ 取消（False）。"""

    async def test_a6_confirm_approved_applies_pending(self, service, mock_repo) -> None:
        """A6【R】confirm approved=True 覆盖：快照旧点 → 物理删旧 → 落新点
        （position 1..N、弧线按名复用不 add_arc）→ pending 移除、snapshot 写入；
        返回 replaced=True、plot_points 2 条新点。
        （RED 期 confirm_replace 方法缺失 → AttributeError FAIL=未实现。）"""
        outline, old1, old2 = _staged_outline()
        existing_arc = _arc("主线", arc_id=ARC_ID, description="追查真凶")
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[old1, old2])
        mock_repo.get_arc_by_name = AsyncMock(return_value=existing_arc)

        result = await service.confirm_replace(TARGET_ID, approved=True)

        assert result["replaced"] is True
        assert result["cancelled"] is False
        assert [p.name for p in result["plot_points"]] == ["新开局", "新收束"]
        assert [p.position for p in result["plot_points"]] == [1, 2]
        assert [p.description for p in result["plot_points"]] == [
            "新开局描述",
            "新收束描述",
        ]
        assert all(p.arc_id == existing_arc.id for p in result["plot_points"])
        mock_repo.add_arc.assert_not_awaited()  # 弧线按名复用，不新建
        assert [c.args[0] for c in mock_repo.hard_delete_point.await_args_list] == [
            OLD1.int,
            OLD2.int,
        ]  # 逐点物理删除旧情节点
        mock_repo.update.assert_awaited_once()
        updated = mock_repo.update.await_args.args[0]
        assert isinstance(updated, Outline)
        assert "replace_pending" not in updated.extra  # 应用后 pending 必须移除
        snapshot = updated.extra["replace_snapshot"]
        assert snapshot["model"] == DEFAULT_MODEL
        assert "replaced_at" in snapshot
        assert snapshot["plot_points"] == [p.model_dump(mode="json") for p in (old1, old2)]

    async def test_a7_confirm_cancelled_clears_pending(self, service, mock_repo) -> None:
        """A7【R】confirm approved=False 取消：只清 pending + repo.update；
        hard_delete_point/add_point/add_arc 全 not awaited（原内容分毫不动）；
        返回 cancelled=True、replaced=False、plot_points/arcs/warnings 空、
        model 回显 pending.model。
        （RED 期 confirm_replace 方法缺失 → AttributeError FAIL。）"""
        outline, old1, old2 = _staged_outline()
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[old1, old2])

        result = await service.confirm_replace(TARGET_ID, approved=False)

        assert result["replaced"] is False
        assert result["cancelled"] is True
        assert result["plot_points"] == []
        assert result["arcs"] == []
        assert result["warnings"] == []
        assert result["model"] == DEFAULT_MODEL
        mock_repo.hard_delete_point.assert_not_awaited()
        mock_repo.add_point.assert_not_awaited()
        mock_repo.add_arc.assert_not_awaited()
        mock_repo.update.assert_awaited_once()
        updated = mock_repo.update.await_args.args[0]
        assert "replace_pending" not in updated.extra
        assert "replace_snapshot" not in updated.extra

    async def test_a8_confirm_without_pending_raises(self, service, mock_repo) -> None:
        """A8【R】confirm 时 pending 缺失（extra 无 replace_pending）→
        OutlineReplaceError，逐字文案「大纲无待确认的覆盖操作」。
        （OutlineReplaceError 为契约新增异常，RED 期不存在 → 函数体内
        import 即 ImportError FAIL=符号未实现。）"""
        from inkflow.domain.ports.outline_errors import OutlineReplaceError

        outline = _outline("无待确认大纲", outline_id=TARGET_ID)  # extra={}
        mock_repo.get = AsyncMock(return_value=outline)
        with pytest.raises(OutlineReplaceError, match="大纲无待确认的覆盖操作"):
            await service.confirm_replace(TARGET_ID, approved=True)

    async def test_a9_confirm_outline_missing_raises(self, service, mock_repo) -> None:
        """A9【R】confirm 目标大纲已删（repo.get→None）→ OutlineNotFoundError。
        （RED 期 confirm_replace 方法缺失 → AttributeError FAIL。）"""
        mock_repo.get = AsyncMock(return_value=None)
        with pytest.raises(OutlineNotFoundError):
            await service.confirm_replace(uuid.uuid4(), approved=True)

    async def test_a12_replace_snapshot_restores_old_points(self, service, mock_repo) -> None:
        """A12【R】快照可恢复（拍板④）：应用后 update 实参 extra
        ["replace_snapshot"]["plot_points"] 逐条 PlotPoint(**item) 还原不抛
        ValidationError，name/position/description/outline_id 与旧点相等。
        （RED 期 confirm_replace 方法缺失 → AttributeError FAIL。）"""
        outline, old1, old2 = _staged_outline()
        existing_arc = _arc("主线", arc_id=ARC_ID)
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[old1, old2])
        mock_repo.get_arc_by_name = AsyncMock(return_value=existing_arc)

        result = await service.confirm_replace(TARGET_ID, approved=True)

        assert result["replaced"] is True
        updated = mock_repo.update.await_args.args[0]
        snapshot = updated.extra["replace_snapshot"]
        restored = [PlotPoint(**item) for item in snapshot["plot_points"]]
        assert [p.name for p in restored] == ["旧点一", "旧点二"]
        assert [p.position for p in restored] == [1, 2]
        assert [p.description for p in restored] == ["旧描述一", "旧描述二"]
        assert [p.outline_id for p in restored] == [TARGET_ID, TARGET_ID]

    async def test_a13_confirm_twice_raises_idempotency(self, service, mock_repo) -> None:
        """A13【R】幂等（拍板④）：confirm(approved=True) 成功应用后 pending 已
        移除——同一 mock repo 直接二次 confirm（任何 approved）→
        OutlineReplaceError「大纲无待确认的覆盖操作」。
        （OutlineReplaceError 契约新增异常，RED 期不存在 → 函数体内 import
        即 ImportError FAIL=符号未实现。）"""
        from inkflow.domain.ports.outline_errors import OutlineReplaceError

        outline, old1, old2 = _staged_outline()
        existing_arc = _arc("主线", arc_id=ARC_ID)
        mock_repo.get = AsyncMock(side_effect=lambda oid: outline)  # 二次读取同一对象
        mock_repo.list_points = AsyncMock(return_value=[old1, old2])
        mock_repo.get_arc_by_name = AsyncMock(return_value=existing_arc)

        first = await service.confirm_replace(TARGET_ID, approved=True)
        assert first["replaced"] is True
        with pytest.raises(OutlineReplaceError, match="大纲无待确认的覆盖操作"):
            await service.confirm_replace(TARGET_ID, approved=False)


class TestConfirmReplaceBranchCoverage:
    """A15-A17【G｜supp】补测：_materialize_replace_points / _stage_replace 未覆盖分支。"""

    async def test_a15_confirm_applies_new_arc_and_unresolvable_warning(
        self, service, mock_repo
    ) -> None:
        """A15 应用覆盖：弧线 add_arc 新建分支 + 点引用新建弧线命中 + 弧线不可解析 warning（765）
        + 无弧线点（755 假分支）+ 空白 arc 串点（757 假分支，视同不挂弧线）。"""
        generated = GeneratedOutline(
            name="覆盖版",
            arcs=[GeneratedArc(name="新弧线")],
            plot_points=[
                GeneratedPlotPoint(name="点一", arc="新弧线"),
                GeneratedPlotPoint(name="点二", arc="缺失弧线"),
                GeneratedPlotPoint(name="点三"),
                GeneratedPlotPoint(name="点四", arc="   "),
            ],
        )
        outline = _outline(
            "目标",
            outline_id=TARGET_ID,
            extra={
                "replace_pending": {
                    "generated": generated.model_dump(mode="json"),
                    "model": DEFAULT_MODEL,
                    "staged_at": "2026-08-02T00:00:00+00:00",
                }
            },
        )
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[])
        mock_repo.get_arc_by_name = AsyncMock(return_value=None)
        result = await service.confirm_replace(TARGET_ID, approved=True)
        assert result["replaced"] is True
        mock_repo.add_arc.assert_awaited_once()
        created_arc = mock_repo.add_arc.await_args.args[0]
        assert created_arc.name == "新弧线"
        assert [p.name for p in result["plot_points"]] == ["点一", "点二", "点三", "点四"]
        assert result["plot_points"][0].arc_id == created_arc.id
        assert result["plot_points"][1].arc_id is None
        assert result["plot_points"][2].arc_id is None  # 无 arc 字段 = 不挂弧线
        assert result["plot_points"][3].arc_id is None  # 空白 arc 串 = 视同无弧线
        assert any("无法解析已跳过关联" in w for w in result["warnings"])
        assert len(result["warnings"]) == 1  # 仅点二产生 warning，点三/四合法静默

    async def test_a16_confirm_empty_plot_points_warning(self, service, mock_repo) -> None:
        """A16 应用覆盖：空情节点 pending → warning「未生成情节点」（784 尾分支）。"""
        generated = GeneratedOutline(name="空点大纲", arcs=[], plot_points=[])
        outline = _outline(
            "目标",
            outline_id=TARGET_ID,
            extra={
                "replace_pending": {
                    "generated": generated.model_dump(mode="json"),
                    "model": DEFAULT_MODEL,
                    "staged_at": "2026-08-02T00:00:00+00:00",
                }
            },
        )
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[])
        result = await service.confirm_replace(TARGET_ID, approved=True)
        assert result["replaced"] is True
        assert result["plot_points"] == []
        assert "未生成情节点" in result["warnings"]

    async def test_a17_generator_stage_defensive_missing_target(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """A17 generator 层防御：暂存期目标大纲不存在 → OutlineNotFoundError（569 守卫分支）。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(plot_points=[{"name": "点", "type": "开篇"}])
        )
        mock_repo.get = AsyncMock(return_value=None)
        with pytest.raises(OutlineNotFoundError):
            await generator.generate(
                OutlineGenerateRequest(project_id=PID, mode="replace", target_outline_id=TARGET_ID),
                project_info="项目名：测试项目",
                default_model=DEFAULT_MODEL,
            )


class TestConfirmReplaceGeneratorGuard:
    """A18【G｜supp】补测：物化委托依赖生成器——未注入 → OutlineServiceError（配置错误）。"""

    async def test_a18_confirm_without_generator_raises(self, mock_repo) -> None:
        """A18 confirm 应用期生成器未注入 → OutlineServiceError「大纲生成器未配置」，
        且零情节点破坏（hard_delete_point/add_point 未调用——物化前失败）。"""
        outline, old1, old2 = _staged_outline()
        mock_repo.get = AsyncMock(return_value=outline)
        mock_repo.list_points = AsyncMock(return_value=[old1, old2])
        svc = OutlineService(repository=mock_repo)  # generator 缺省 None
        with pytest.raises(OutlineServiceError, match="大纲生成器未配置"):
            await svc.confirm_replace(TARGET_ID, approved=True)
        mock_repo.hard_delete_point.assert_not_awaited()
        mock_repo.add_point.assert_not_awaited()
