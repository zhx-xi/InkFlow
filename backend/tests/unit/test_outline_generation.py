"""F11 大纲生成管线单元测试 — Mock LLM + Mock PromptManager + Mock Repo.

覆盖 spec §9「生成（Mock LLM，遵循 ADR-015）」全部场景:
合法 JSON 全量落库（position 1..N）/ 大纲名回退与缺省 / 弧线按名复用 /
弧线引用无法解析 / 非法条目跳过 / 同名冲突 422 /
围栏输出提取 / 修复重试与异常透传 / 空情节点 warning / save=false 零落库 /
模板与模型参数断言 / num_chapters 条件段解析（真实 PromptManager）。

依据: specs/f11-outline/spec.md §5（AI 生成模式，差异见 §5.6）+
§9 测试策略。实现镜像 F10 test_world_extraction.py，仅替换领域实体
（Outline/PlotPoint/StoryArc ↔ WorldSetting）与模板名
（outline_generate ↔ world_extract），并新增生成模式专属场景
（save 两态 / 弧线复用 / 大纲同名冲突 / num_chapters 处理）。

"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.outline import (
    GeneratedOutline,
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    StoryArc,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import OutlineGenerationError, OutlineNameConflictError
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._outline_generator import (
    OutlineGenerator,
    _extract_json_fragment,
    _first_error,
    _resolve_num_chapters_in_text,
    _to_int_id,
)
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
DEFAULT_MODEL = "openai/gpt-4o"


def _outline(name: str, description: str = "") -> Outline:
    """构造测试用大纲实体（默认时间戳固定，便于断言）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def _arc(name: str, description: str = "") -> StoryArc:
    """构造测试用故事弧线实体。"""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        description=description,
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


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    """Mock PromptManager — 渲染结果模拟 str.replace 透传 Jinja2 条件段。

    F5 PromptManager._format 只做 {key} 字面替换，outline_generate.yaml 中的
    {% if num_chapters %} 条件段会原样透传；generator 负责在渲染后清理
    （_resolve_num_chapters_in_text），本 fixture 忠实模拟该行为。
    """
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
                    "content": "项目信息：\n项目名：雾都谜案\n\n创作约束：\n悬疑推理",
                },
            ],
            token_estimate=80,
        )
    )
    return pm


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get_arc_by_name = AsyncMock(return_value=None)
    repo.add_arc = AsyncMock(side_effect=lambda a: a)
    repo.add_point = AsyncMock(side_effect=lambda p: p)
    return repo


@pytest.fixture
def generator(mock_llm, mock_prompt_manager, mock_repo) -> OutlineGenerator:
    return OutlineGenerator(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        repository=mock_repo,
    )


class TestOutlineGenerator:
    """生成管线测试 — 解析 / 重试 / 落库两态 / 弧线复用 / 幂等注意（Mock LLM）。"""

    async def test_valid_json_saves_outline_points_and_arcs(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """合法 JSON → save=true 全落库：大纲/弧线/情节点计数正确，position 从 1 递增。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                outline={"name": "雾都谜案大纲", "description": "侦探小说总体设计"},
                arcs=[
                    {"name": "主线", "description": "追查真凶"},
                    {"name": "感情线", "description": "主角与助手"},
                ],
                plot_points=[
                    {
                        "name": "开篇命案",
                        "type": "开篇",
                        "description": "雨夜命案发生",
                        "arc": "主线",
                    },
                    {
                        "name": "线索浮现",
                        "type": "发展",
                        "description": "发现关键线索",
                        "arc": "主线",
                    },
                    {
                        "name": "真凶落网",
                        "type": "高潮",
                        "description": "真凶身份揭晓",
                        "arc": "感情线",
                    },
                ],
            )
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert isinstance(result, OutlineGenerationResult)
        assert result.saved is True
        assert result.outline is not None
        assert result.outline.name == "雾都谜案大纲"
        assert result.outline.description == "侦探小说总体设计"
        assert result.outline.project_id == PID
        assert [p.name for p in result.plot_points] == ["开篇命案", "线索浮现", "真凶落网"]
        assert [p.position for p in result.plot_points] == [1, 2, 3]  # 按输出顺序 1..N
        assert result.plot_points[0].arc_id == result.arcs[0].id  # 弧线名解析挂接
        assert result.plot_points[2].arc_id == result.arcs[1].id
        assert len(result.arcs) == 2
        assert result.warnings == []
        assert result.model == DEFAULT_MODEL
        assert mock_repo.add.await_count == 1
        assert mock_repo.add_arc.await_count == 2
        assert mock_repo.add_point.await_count == 3

    async def test_outline_name_falls_back_to_request_name(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """LLM 未给大纲名 → 回退请求 name。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(outline={"description": "无名字大纲"}, plot_points=[{"name": "开篇"}])
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID, name="我的规划"),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.outline is not None
        assert result.outline.name == "我的规划"
        assert result.outline.description == "无名字大纲"

    async def test_default_outline_name_when_all_missing(self, generator, mock_llm) -> None:
        """LLM 与请求均无大纲名 → 缺省「未命名大纲」。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(outline={"name": None}, plot_points=[{"name": "开篇"}])
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.outline is not None
        assert result.outline.name == "未命名大纲"

    async def test_arc_reuse_by_name(self, generator, mock_llm, mock_repo) -> None:
        """库中已有同名活动弧线 → 复用（不新建、不覆盖描述），情节点挂既有 arc_id。"""
        existing = _arc(name="主线", description="旧说明")
        mock_repo.get_arc_by_name = AsyncMock(return_value=existing)
        mock_llm.chat.return_value = _ok_response(
            _payload(
                arcs=[{"name": "主线", "description": "新说明"}],
                plot_points=[{"name": "开篇命案", "arc": "主线"}],
            )
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert mock_repo.add_arc.await_count == 0  # 不新建
        assert len(result.arcs) == 1
        assert result.arcs[0].id == existing.id  # 复用实例
        assert result.arcs[0].description == "旧说明"  # 不覆盖描述
        assert result.plot_points[0].arc_id == existing.id

    async def test_unresolvable_arc_skips_link_with_warning(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """情节点 arc 引用无法解析（不在弧线列表且库中不存在）→ 照常创建 + warning。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(plot_points=[{"name": "开篇命案", "arc": "幻觉弧线"}])
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert len(result.plot_points) == 1
        assert result.plot_points[0].arc_id is None  # 跳过关联
        assert any("幻觉弧线" in w and "无法解析" in w for w in result.warnings)

    async def test_invalid_entries_skipped_with_warning(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """非法条目（空名/超长）→ 跳过 + warning，其余正常落库。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                arcs=[{"name": ""}, {"name": "主线"}],
                plot_points=[
                    {"name": ""},
                    {"name": "长" * 101},
                    {"name": "开篇命案", "type": "开篇", "description": "主角登场", "arc": "主线"},
                    {"name": "真凶落网", "arc": "主线"},
                ],
            )
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert len(result.plot_points) == 2  # 2 个非法情节点被跳过
        assert len(result.arcs) == 1  # 空名弧线被跳过
        assert len(result.warnings) == 3
        assert all("跳过" in w for w in result.warnings)
        # 情节点 arc 名解析到本批新建的弧线
        assert result.plot_points[0].arc_id == result.arcs[0].id

    async def test_name_conflict_raises(self, generator, mock_llm, mock_repo) -> None:
        """同名活动大纲已存在 + save=true → OutlineNameConflictError（422 语义，零写入）。"""
        mock_repo.get_by_name = AsyncMock(return_value=_outline(name="雾都谜案大纲"))
        mock_llm.chat.return_value = _ok_response(_payload())
        with pytest.raises(OutlineNameConflictError):
            await generator.generate(
                OutlineGenerateRequest(project_id=PID),
                project_info="项目名：雾都谜案",
                default_model=DEFAULT_MODEL,
            )
        assert mock_repo.add.await_count == 0
        assert mock_repo.add_arc.await_count == 0
        assert mock_repo.add_point.await_count == 0

    async def test_fenced_output_extracts_json_fragment(self, generator, mock_llm) -> None:
        """输出带围栏/前后缀文字 → _extract_json_fragment 提取成功。"""
        payload = _payload(plot_points=[{"name": "开篇命案"}])
        fenced = f"好的，以下是生成的大纲：\n```json\n{payload}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert len(result.plot_points) == 1
        assert result.plot_points[0].name == "开篇命案"

    async def test_invalid_output_retries_twice_then_raises(self, generator, mock_llm) -> None:
        """输出完全非法 → 修复重试 2 次（共 3 次调用）→ OutlineGenerationError。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="这不是 JSON", model=DEFAULT_MODEL),
            ChatResponse(content="还是不对", model=DEFAULT_MODEL),
            ChatResponse(content="依然失败", model=DEFAULT_MODEL),
        ]
        with pytest.raises(OutlineGenerationError) as excinfo:
            await generator.generate(
                OutlineGenerateRequest(project_id=PID),
                project_info="项目名：雾都谜案",
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 3
        assert excinfo.value.raw_output == "依然失败"
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(只输出 JSON)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "只输出 JSON" in call2_msgs[-1].content
        # 第 3 次调用保留完整对话历史
        call3_msgs = mock_llm.chat.await_args_list[2].args[0]
        assert call3_msgs[-2].content == "还是不对"

    async def test_llm_error_propagates_without_retry(self, generator, mock_llm) -> None:
        """Mock LLM 抛 LLMRequestError → 透传，不消耗解析重试。"""
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await generator.generate(
                OutlineGenerateRequest(project_id=PID),
                project_info="项目名：雾都谜案",
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 1

    async def test_llm_error_after_bad_output_propagates(self, generator, mock_llm) -> None:
        """坏输出后 LLM 报错 → 立即透传，不进入第 3 次尝试。"""
        mock_llm.chat.side_effect = [
            ChatResponse(content="bad", model=DEFAULT_MODEL),
            LLMRequestError("timeout"),
        ]
        with pytest.raises(LLMRequestError):
            await generator.generate(
                OutlineGenerateRequest(project_id=PID),
                project_info="项目名：雾都谜案",
                default_model=DEFAULT_MODEL,
            )
        assert mock_llm.chat.await_count == 2

    async def test_empty_plot_points_warns(self, generator, mock_llm, mock_repo) -> None:
        """空情节点列表 → 大纲/弧线照常落库 + warning「未生成情节点」。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(outline={"name": None}, arcs=[{"name": "主线"}])
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.outline is not None
        assert result.outline.name == "未命名大纲"  # 大纲名缺省回退
        assert result.plot_points == []
        assert len(result.arcs) == 1
        assert any("未生成情节点" in w for w in result.warnings)

    async def test_save_false_returns_preview_without_persisting(
        self, generator, mock_llm, mock_repo
    ) -> None:
        """save=false → 返回 preview（GeneratedOutline），零落库、不做同名检查。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(
                outline={"name": "预览大纲", "description": "预览描述"},
                arcs=[{"name": "主线"}],
                plot_points=[{"name": "开篇命案", "arc": "主线"}],
            )
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID, save=False),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert result.saved is False
        assert result.outline is None
        assert result.plot_points == []
        assert result.arcs == []
        assert result.preview is not None
        assert isinstance(result.preview, GeneratedOutline)
        assert result.preview.name == "预览大纲"
        assert result.preview.description == "预览描述"
        assert len(result.preview.plot_points) == 1
        assert len(result.preview.arcs) == 1
        # 零落库：不创建任何实体、不做同名检查
        for method in (
            mock_repo.get_by_name,
            mock_repo.add,
            mock_repo.get_arc_by_name,
            mock_repo.add_arc,
            mock_repo.add_point,
        ):
            method.assert_not_awaited()

    async def test_uses_template_default_model_and_temperature(
        self, generator, mock_llm, mock_prompt_manager
    ) -> None:
        """断言使用 outline_generate 模板 + 变量 project_info/prompt/num_chapters
        + 默认模型 + temperature 0.2。"""
        mock_llm.chat.return_value = _ok_response(_payload(plot_points=[{"name": "开篇命案"}]))
        await generator.generate(
            OutlineGenerateRequest(project_id=PID, prompt="悬疑推理"),
            project_info="项目名：雾都谜案\n类型：悬疑",
            default_model=DEFAULT_MODEL,
        )
        mock_prompt_manager.load.assert_called_once_with("outline_generate")
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(
            template,
            {
                "project_info": "项目名：雾都谜案\n类型：悬疑",
                "prompt": "悬疑推理",
                "num_chapters": "",  # num_chapters 缺省 → 空串占位（str.replace 无残留）
            },
        )
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["temperature"] == 0.2
        msgs = mock_llm.chat.await_args.args[0]
        assert msgs[0].role == "system"
        assert msgs[-1].role == "user"

    async def test_request_model_overrides_default(self, generator, mock_llm) -> None:
        """request.model 覆盖项目默认模型。"""
        mock_llm.chat.return_value = _ok_response(_payload())
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID, model="deepseek/deepseek-chat"),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert mock_llm.chat.await_args.kwargs["model"] == "deepseek/deepseek-chat"
        assert result.model == "deepseek/deepseek-chat"

    async def test_num_chapters_rendered_into_prompt(self, mock_llm, mock_repo) -> None:
        """num_chapters 有值 → 条件段解析：占位符替换为数字，
        无字面 Jinja 标记残留（真实 PromptManager）。"""
        mock_llm.chat.return_value = _ok_response(_payload(plot_points=[{"name": "开篇命案"}]))
        generator = OutlineGenerator(
            llm_client=mock_llm,
            prompt_manager=LangChainPromptManager(),  # 真实 str.replace 渲染
            repository=mock_repo,
        )
        await generator.generate(
            OutlineGenerateRequest(project_id=PID, prompt="悬疑推理", num_chapters=12),
            project_info="项目名：雾都谜案\n类型：悬疑",
            default_model=DEFAULT_MODEL,
        )
        msgs = mock_llm.chat.await_args.args[0]
        system = msgs[0].content
        assert "情节点数量控制在约 12 个" in system
        assert "{%" not in system
        assert "{{" not in system
        assert "}}" not in system
        user = msgs[-1].content
        assert "项目名：雾都谜案" in user
        assert "悬疑推理" in user

    # ── _parse_output 结构级错误分支 ──────────────────────────────

    def test_malformed_json_syntax_returns_syntax_error(self, generator) -> None:
        """括号平衡但语法非法 → JSON 语法错误（json.JSONDecodeError 分支）。"""
        outcome = generator._parse_output('{"a": }')
        assert not outcome.ok
        assert "JSON 语法错误" in outcome.error

    def test_outline_missing_uses_empty_data(self, generator) -> None:
        """payload 无 outline 键 → 空 outline_data（name/description 回退）。"""
        outcome = generator._parse_output('{"arcs": [], "plot_points": []}')
        assert outcome.ok
        assert outcome.generated is not None
        assert outcome.generated.name is None
        assert outcome.generated.description is None

    def test_outline_not_dict_returns_error(self, generator) -> None:
        """outline 字段非对象 → 结构错误。"""
        outcome = generator._parse_output('{"outline": "oops"}')
        assert outcome.error == "outline 字段必须是对象"

    def test_arcs_not_list_returns_error(self, generator) -> None:
        """arcs 字段非列表 → 结构错误。"""
        outcome = generator._parse_output('{"outline": {}, "arcs": "x", "plot_points": []}')
        assert outcome.error == "arcs 字段必须是列表"

    def test_plot_points_not_list_returns_error(self, generator) -> None:
        """plot_points 字段非列表 → 结构错误。"""
        outcome = generator._parse_output('{"outline": {}, "arcs": [], "plot_points": 3}')
        assert outcome.error == "plot_points 字段必须是列表"

    def test_outline_schema_invalid_returns_error(self, generator) -> None:
        """大纲级 schema 校验失败（name 超长）→ 整体重试错误。"""
        raw = '{"outline": {"name": "' + "长" * 51 + '"}}'
        outcome = generator._parse_output(raw)
        assert "大纲 schema 校验失败" in outcome.error

    async def test_whitespace_arc_skips_link_silently(self, generator, mock_llm) -> None:
        """情节点 arc 为纯空白 → 视为未指定：不尝试解析、无「无法解析」warning。"""
        mock_llm.chat.return_value = _ok_response(
            _payload(plot_points=[{"name": "开篇命案", "arc": "   "}])
        )
        result = await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        assert len(result.plot_points) == 1
        assert result.plot_points[0].arc_id is None
        assert not any("无法解析" in w for w in result.warnings)


class TestOutlineGeneratorHelpers:
    """模块级纯函数测试（_to_int_id / _first_error / _resolve_num_chapters_in_text）。"""

    def test_to_int_id_passthrough_for_int(self) -> None:
        """int 输入原样返回（非 UUID 分支）。"""
        assert _to_int_id(42) == 42

    def test_first_error_with_empty_errors_returns_str(self) -> None:
        """errors() 为空 → 回退 str(err)。"""
        err = ValidationError.from_exception_data("测试", line_errors=[])
        assert _first_error(err) == str(err)

    def test_resolve_num_chapters_removes_unclosed_if_tag(self) -> None:
        """num_chapters=None 且模板缺 {% endif %} 闭标签 → 仅去除开标签防死循环。"""
        text = "开头 {% if num_chapters %} 中间"
        assert _resolve_num_chapters_in_text(text, None) == "开头  中间"


class TestNumChaptersConditional:
    """num_chapters 条件段解析（真实 PromptManager 渲染，镜像 F11 §5.6 差异）。"""

    async def test_num_chapters_none_removes_conditional(self, mock_llm, mock_repo) -> None:
        """num_chapters 缺省 → 整段条件移除，不注入章节数提示，无字面 Jinja 标记残留。"""
        mock_llm.chat.return_value = _ok_response(_payload(plot_points=[{"name": "开篇命案"}]))
        generator = OutlineGenerator(
            llm_client=mock_llm,
            prompt_manager=LangChainPromptManager(),
            repository=mock_repo,
        )
        await generator.generate(
            OutlineGenerateRequest(project_id=PID),
            project_info="项目名：雾都谜案",
            default_model=DEFAULT_MODEL,
        )
        msgs = mock_llm.chat.await_args.args[0]
        system = msgs[0].content
        assert "情节点数量控制在约" not in system
        assert "{%" not in system
        assert "{{" not in system
        assert "}}" not in system


class TestExtractJsonFragment:
    """_extract_json_fragment 纯函数测试。"""

    def test_balanced_nested_with_braces_in_string(self) -> None:
        """嵌套括号与字符串内花括号均正确处理。"""
        text = '前缀 {"a": {"b": [1, 2]}, "c": "}"} 后缀'
        assert _extract_json_fragment(text) == '{"a": {"b": [1, 2]}, "c": "}"}'

    def test_unbalanced_or_absent_returns_none(self) -> None:
        """无花括号或括号不平衡 → None。"""
        assert _extract_json_fragment("纯文本输出") is None
        assert _extract_json_fragment('{"a": 1') is None

    def test_escaped_quotes_inside_string(self) -> None:
        """字符串字面量内的转义引号不提前闭合字符串（escaped 状态机分支）。"""
        text = '{"msg": "他说 \\"你好\\""}'
        assert _extract_json_fragment(text) == text
