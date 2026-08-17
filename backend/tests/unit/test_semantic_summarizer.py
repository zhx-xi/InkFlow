"""F45 M2 语义总结管线 RED 契约测试 — SemanticSummarizer（全 mock LLM 轨，镜像 F16）.

依据: specs/f45-memory-evolution/spec.md §2.3（SemanticSummary 模型）/§5.3
（LLM 总结管线①-⑥）/§5.3.1（防幻觉 B 测试契约）/§5.4（anchor_hash）/§9
测试策略第 3 行 ⑪-⑰/§13 M2-1/M2-2；镜像 F16 test_style_llm_analyzer.py
（mock LLM 形态: MagicMock(spec=LLMClientProtocol) + chat=AsyncMock +
mock_prompt_manager fixture + _payload/_ok_response helper）与
_style_llm_analyzer.py（_extract_json_fragment/修复式重试/_ParseOutcome 模式）。

RED 预期形态
------------
被测模块 inkflow.domain.services.semantic_summarizer 整体不存在 → 顶部
`from inkflow.domain.services import semantic_summarizer`（父包 from-import
形态——RED 期缺失模块直路径 import 会被 isort 判 third-party → I001，
父包存在则 first-party 零 churn）→ 收集期 ImportError: cannot import name
'semantic_summarizer' from 'inkflow.domain.services'（等价 ModuleNotFoundError
收集错误，1 error，exit 2）。顶部仅此一个 inkflow import；其余 M2 新符号
（SemanticSummary / SemanticSummaryError）一律用例体惰性 import——避免
多缺失模块顶部 import 报字母序首个（models 先于 services）导致 RED 根因
漂移。GREEN 后全部可解析 → 14 用例全绿。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
新建模块 inkflow.domain.services.semantic_summarizer:

    class SemanticSummarizer:
        def __init__(self, *, llm_client, prompt_manager): ...
        async def summarize(self, anchors: list, *, scope, project_id,
                            anchor_hash, model) -> tuple[SemanticSummary | None, int]:
            # 返回 (summary, dropped)；dropped = 防幻觉 B 丢弃条数
            # ① anchors 空 → (None, 0) 不调用 LLM
            # ② 渲染模板 memory_semantic_summary（变量 {anchors}）→ ChatMessage 包装
            # ③ llm_client.chat(messages, model=model, temperature=0.2)
            # ④ _extract_json_fragment 提取 → json.loads → 校验顶层对象含
            #    "project_specific" 与 "user_general" 两组（每组元素为
            #    {"content": str 非空, "anchor_refs": [str]}）——缺组/缺字段/类型错 → 重试
            # ⑤ 按 scope 取对应组（PROJECT→project_specific；USER→user_general）；
            #    每条 anchor_refs 必须 ⊆ 锚点 value 集合（防幻觉 B），
            #    不通过丢弃该条（dropped+=1）
            # ⑥ 修复式重试 ≤2（共 3 次尝试）→ 仍失败 → SemanticSummaryError
            # ⑦ content = 剩余条目 content 逐行拼接（"\n".join）截断 ≤2000 字符；
            #    剩余空 → (None, dropped)；非空 → SemanticSummary(
            #    id=uuid4 str, scope, project_id, content, anchor_hash,
            #    anchor_count=len(anchors), model, created_at/updated_at=UTC now)
        # 模块级 helper（同 F16 命名）:
        #   _extract_json_fragment(text) -> str | None（镜像 F16 同款逻辑）
        #   _build_fix_prompt(error_detail) -> str（镜像 F16）
        #   _ParseOutcome 等价物（error/ok）

- 顶部 import 形态: `from inkflow.domain.services import semantic_summarizer`
  + 模块级别名 `SemanticSummarizer = semantic_summarizer.SemanticSummarizer`
  （RED 收集错误根因唯一化；GREEN 后别名解析为类，测试体裸名引用镜像 F16）。
- SemanticSummaryError 位于 inkflow.domain.ports.semantic_summary_errors.py
  （本测试用例体惰性 import，仅断言异常类型，不约束构造参数语义）。
- SemanticSummary 模型（spec §2.3 逐字）: SummaryScope(StrEnum)
  PROJECT="project"/USER="user"；SemanticSummary(BaseModel, from_attributes):
  id:str / scope:SummaryScope / project_id:uuid.UUID|None=None / content:str /
  anchor_hash:str / anchor_count:int / model:str / created_at:datetime /
  updated_at:datetime。
- 锚点 value 集合语义: anchor_refs 校验用锚点对象的 .value 字段集合
  （ProjectPreference/UserPreference 均有 .value；本测试按 scope 分别构造）。
- 模板名 _TEMPLATE_NAME = "memory_semantic_summary"；渲染变量 {anchors} 传
  原始 anchors 列表（镜像 F16 {text} 传原始文本）；渲染后消息经 ChatMessage 包装。
- scope 参数传字符串字面量（SCOPE_PROJECT/SCOPE_USER，StrEnum 成员与字符串
  相等比较成立，GREEN 签名 scope: SummaryScope 亦兼容）。
- LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。
- spec §9 ⑯⑰（幂等 anchor_hash 未变不调 LLM / 锚点变化重新总结）属
  memory_service 编排层（summarize 编排 + 锚点哈希，spec §8 M2），
  不在本管线文件范围。

用例清单（全部 mock LLM，不调真实 API）:
1.  test_anchors_empty_returns_none: anchors=[] → (None, 0)，chat 不被调用
2.  test_valid_json_project_scope: scope=PROJECT 合法 JSON → SemanticSummary
    （content 拼接/anchor_count/anchor_hash/model/project_id/时区感知）
3.  test_valid_json_user_scope: scope=USER → project_id is None、scope=user
4.  test_fenced_json_extracted: ```json 围栏包裹 → 提取成功
5.  test_invalid_json_retries_twice_then_raises: 3 次全非法 →
    SemanticSummaryError（await_count==3；第 2 次调用含 assistant+user 修复提示）
6.  test_invalid_json_recovers_on_retry: 首次非法二次合法 → 成功（await_count==2）
7.  test_missing_group_retries: 缺 project_specific 组 → 重试后成功
8.  test_content_empty_retries: 组内 content 为空 → 重试后成功
9.  test_hallucination_anchor_refs_outside_set_dropped: 证据集外 anchor_refs →
    该条丢弃 dropped==1，合法条保留（-k hallucination 命中，§13 M2-2）
10. test_hallucination_all_dropped_returns_none: 全部越界 → (None, N) 静默丢弃
11. test_content_truncated_to_2000: content 超长 → 截断 ≤2000 字符
12. test_temperature_and_model_passed: llm.chat kwargs model/temperature==0.2 +
    模板渲染 {anchors} 注入（spec §9 ⑫）
13. test_llm_request_error_propagates: LLMRequestError → 透传（await_count==1）
14. test_project_specific_used_only_for_project_scope: scope=PROJECT 时
    user_general 组不参与校验/不进 content（投影正确）

asyncio 模式: pytest-asyncio mode=Mode.AUTO（pyproject asyncio_mode = "auto"）；
文件级 pytestmark = pytest.mark.asyncio 双保险（STRICT/AUTO 两种模式均成立），
全部用例 async def。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.preference import PreferenceCategory, ProjectPreference
from inkflow.domain.models.user_preference import UserPreference
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services import semantic_summarizer

# 模块级别名: RED 期父包 from-import 收集错误 = ImportError: cannot import name
# 'semantic_summarizer' from 'inkflow.domain.services'（等价 ModuleNotFoundError
# 收集错误，exit 2）；GREEN 后模块存在 → 别名解析为类，测试体裸名引用镜像 F16。
SemanticSummarizer = semantic_summarizer.SemanticSummarizer

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
MODEL = "deepseek/deepseek-v4-flash"  # #415 唯一默认源，测试显式传入
TEMPLATE_NAME = "memory_semantic_summary"
ANCHOR_HASH = "sha256-" + "a" * 64
SCOPE_PROJECT = "project"
SCOPE_USER = "user"


def _summary_model():
    """惰性导入 SemanticSummary（RED 阶段 domain/models/semantic_summary.py 未实现）。"""
    from inkflow.domain.models.semantic_summary import SemanticSummary

    return SemanticSummary


def _entry(
    content: str = "叙述偏好：称呼主角用全名「林晚」而非代词",
    anchor_refs: list[str] | None = None,
) -> dict:
    """构造单条抽象偏好（content + anchor_refs，spec §5.3.1 契约）。"""
    refs = anchor_refs if anchor_refs is not None else ["林晚"]
    return {"content": content, "anchor_refs": refs}


def _payload(project_specific: list | None = None, user_general: list | None = None) -> str:
    """构造合法语义总结 JSON（project_specific/user_general 两组，spec §5.3 ④）。"""
    return json.dumps(
        {
            "project_specific": project_specific
            if project_specific is not None
            else [
                _entry(content="叙述偏好：称呼主角用全名「林晚」而非代词"),
                _entry(content="章节开头用场景描写而非直接对话", anchor_refs=["林晚", "低声道"]),
            ],
            "user_general": user_general
            if user_general is not None
            else [_entry(content="用户通用风格：句长偏短（≤20 字为主）", anchor_refs=["低声道"])],
        },
        ensure_ascii=False,
    )


def _ok_response(
    payload: str | None = None,
    *,
    project_specific: list | None = None,
    user_general: list | None = None,
) -> ChatResponse:
    """构造 Mock LLM 成功响应（payload 或 project_specific/user_general 二选一）。

    project_specific/user_general 关键字形态转发给 _payload 组装 JSON——
    GREEN 复验时 Codex 上报「4 用例 TypeError: unexpected keyword argument
    'project_specific'」（helper 签名不自洽，实现未触达），父侧裁定测试缺陷直修。
    """
    if payload is None:
        payload = _payload(
            project_specific=project_specific,
            user_general=user_general,
        )
    return ChatResponse(content=payload, model=MODEL)


def _project_anchor(value: str) -> ProjectPreference:
    """构造项目级锚点（scope=project 的 difflib 已落库偏好，spec §5.3 输入）。"""
    return ProjectPreference(
        id=str(uuid.uuid4()),
        project_id=PID,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value=value,
        confidence=0.75,
        count=2,
        source_events=[str(uuid.uuid4())],
        created_at=TS,
        updated_at=TS,
    )


def _user_anchor(value: str) -> UserPreference:
    """构造用户级锚点（scope=user 的跨项目已落库偏好，spec §5.3 输入）。"""
    return UserPreference(
        id=str(uuid.uuid4()),
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value=value,
        confidence=0.75,
        count=2,
        project_count=2,
        source_projects=[str(PID), str(uuid.uuid4())],
        source_events=[str(uuid.uuid4())],
        created_at=TS,
        updated_at=TS,
    )


def _anchors(scope: str, values: list[str]) -> list:
    """按 scope 构造锚点列表（project → ProjectPreference；user → UserPreference）。"""
    if scope == SCOPE_PROJECT:
        return [_project_anchor(v) for v in values]
    return [_user_anchor(v) for v in values]


pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM 客户端（chat 为 AsyncMock，镜像 F16 形态）。"""
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    """Mock Prompt 管理器（load 返回 memory_semantic_summary 模板，render 返回渲染消息）。"""
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name=TEMPLATE_NAME,
        description="Memory semantic summary template",
        system_prompt="你是写作偏好归纳器。输出严格 JSON。",
        human_prompt="锚点：\n{anchors}",
        variables=["anchors"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是写作偏好归纳器。输出严格 JSON。"},
                {"role": "user", "content": "锚点：\n- 林晚（style_word）\n- 低声道（style_word）"},
            ],
            token_estimate=100,
        )
    )
    return pm


@pytest.fixture
def summarizer(mock_llm: MagicMock, mock_prompt_manager: MagicMock) -> SemanticSummarizer:
    """装配 SemanticSummarizer（Mock LLM + Mock PromptManager 注入，ADR-015）。"""
    return SemanticSummarizer(llm_client=mock_llm, prompt_manager=mock_prompt_manager)


class TestSemanticSummarizer:
    """语义总结管线测试 — 解析 / 修复重试 / 防幻觉 B / 截断（全 mock LLM）。"""

    async def test_anchors_empty_returns_none(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """① 锚点为空 → (None, 0)，不调用 LLM（spec §5.3 ①/§9 ⑪）。"""
        result = await summarizer.summarize(
            [], scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert result == (None, 0)
        mock_llm.chat.assert_not_awaited()

    async def test_valid_json_project_scope(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """②-⑦ scope=PROJECT: 合法 JSON → SemanticSummary（content 拼接/字段/时区感知）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.return_value = _ok_response(_payload())
        summary, dropped = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert dropped == 0
        assert summary.scope == SCOPE_PROJECT
        assert summary.project_id == PID
        assert summary.anchor_hash == ANCHOR_HASH
        assert summary.anchor_count == len(anchors)
        assert summary.model == MODEL
        assert summary.content == (
            "叙述偏好：称呼主角用全名「林晚」而非代词\n章节开头用场景描写而非直接对话"
        )
        assert summary.created_at.tzinfo is not None  # UTC 时区感知
        assert summary.updated_at.tzinfo is not None
        assert mock_llm.chat.await_count == 1

    async def test_valid_json_user_scope(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤ scope=USER: 取 user_general 组 → 总结 project_id is None、scope=user。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_USER, ["低声道"])
        mock_llm.chat.return_value = _ok_response(_payload())
        summary, dropped = await summarizer.summarize(
            anchors, scope=SCOPE_USER, project_id=None, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert dropped == 0
        assert summary.scope == SCOPE_USER
        assert summary.project_id is None
        assert summary.anchor_count == len(anchors)
        assert summary.anchor_hash == ANCHOR_HASH
        assert summary.content == "用户通用风格：句长偏短（≤20 字为主）"
        assert mock_llm.chat.await_count == 1

    async def test_fenced_json_extracted(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """④ 代码块围栏/前后缀文字包裹 → _extract_json_fragment 提取成功（镜像 F16）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        fenced = f"好的，以下是语义总结：\n```json\n{_payload()}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        summary, _ = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert summary.content == (
            "叙述偏好：称呼主角用全名「林晚」而非代词\n章节开头用场景描写而非直接对话"
        )

    async def test_invalid_json_retries_twice_then_raises(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤⑥ 输出完全非法 → 修复重试 2 次（共 3 次调用）→ SemanticSummaryError。"""
        from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError

        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response("还是不对"),
            _ok_response("依然失败"),
        ]
        with pytest.raises(SemanticSummaryError):
            await summarizer.summarize(
                anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
            )
        assert mock_llm.chat.await_count == 3  # 首次 + 2 次修复重试
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(修复提示，附错误信息)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "JSON" in call2_msgs[-1].content

    async def test_invalid_json_recovers_on_retry(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤⑥ 非法输出后修复重试成功 → 返回总结（共 2 次调用，spec §9 ⑭）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response(_payload()),
        ]
        summary, _ = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert summary.content == (
            "叙述偏好：称呼主角用全名「林晚」而非代词\n章节开头用场景描写而非直接对话"
        )
        assert mock_llm.chat.await_count == 2

    async def test_missing_group_retries(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """④ 输出缺 project_specific 组 → 视为不可解析 → 修复重试后成功（共 2 次调用）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        missing_group = json.dumps(
            {"user_general": [_entry(content="用户通用风格：句长偏短", anchor_refs=["低声道"])]},
            ensure_ascii=False,
        )
        mock_llm.chat.side_effect = [_ok_response(missing_group), _ok_response(_payload())]
        summary, _ = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert summary.content == (
            "叙述偏好：称呼主角用全名「林晚」而非代词\n章节开头用场景描写而非直接对话"
        )
        assert mock_llm.chat.await_count == 2

    async def test_content_empty_retries(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """④ 组内 content 为空字符串 → 元素校验失败 → 修复重试后成功（共 2 次调用）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        bad_payload = _payload(project_specific=[_entry(content="", anchor_refs=["林晚"])])
        mock_llm.chat.side_effect = [_ok_response(bad_payload), _ok_response(_payload())]
        summary, _ = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert mock_llm.chat.await_count == 2

    async def test_hallucination_anchor_refs_outside_set_dropped(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤ 防幻觉 B: anchor_refs 含证据集外 value → 该条丢弃（dropped+=1），
        剩余合法条保留进 content（spec §5.3.1/§13 M2-2，-k hallucination 命中）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        hallucinated = _entry(content="用户喜欢用比喻修辞", anchor_refs=["比喻"])
        mock_llm.chat.return_value = _ok_response(
            project_specific=[_entry(), hallucinated], user_general=[_entry()]
        )
        summary, dropped = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert dropped == 1
        assert summary.content == "叙述偏好：称呼主角用全名「林晚」而非代词"  # 仅合法条保留
        assert "比喻" not in summary.content
        assert mock_llm.chat.await_count == 1

    async def test_hallucination_all_dropped_returns_none(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤⑦ 全部条目 anchor_refs 非法 → (None, N)（静默丢弃不抛错，spec §7）。"""
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.return_value = _ok_response(
            project_specific=[
                _entry(content="编造的偏好一", anchor_refs=["比喻"]),
                _entry(content="编造的偏好二", anchor_refs=["排比"]),
            ],
            user_general=[_entry()],
        )
        summary, dropped = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert summary is None
        assert dropped == 2
        assert mock_llm.chat.await_count == 1

    async def test_content_truncated_to_2000(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑦ content 超长 → 截断 ≤2000 字符（拼接后截断，spec §5.3 ⑥）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.return_value = _ok_response(
            project_specific=[
                _entry(content="长" * 1500, anchor_refs=["林晚"]),
                _entry(content="长" * 1500, anchor_refs=["低声道"]),
            ],
            user_general=[_entry()],
        )
        summary, _ = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert len(summary.content) == 2000
        assert summary.content == ("长" * 1500 + "\n" + "长" * 1500)[:2000]

    async def test_temperature_and_model_passed(
        self,
        summarizer: SemanticSummarizer,
        mock_llm: MagicMock,
        mock_prompt_manager: MagicMock,
    ) -> None:
        """②③ 模板渲染 {anchors} 注入 + llm.chat kwargs: model==传入 model、temperature==0.2。"""
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.return_value = _ok_response(_payload())
        await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == MODEL
        assert kwargs["temperature"] == 0.2
        # ② 模板渲染（spec §9 ⑫）: memory_semantic_summary 模板 + 变量 {anchors}
        mock_prompt_manager.load.assert_called_once_with(TEMPLATE_NAME)
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(template, {"anchors": anchors})

    async def test_llm_request_error_propagates(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """③ LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。"""
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await summarizer.summarize(
                anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
            )
        assert mock_llm.chat.await_count == 1

    async def test_project_specific_used_only_for_project_scope(
        self, summarizer: SemanticSummarizer, mock_llm: MagicMock
    ) -> None:
        """⑤ scope=PROJECT 时 user_general 组不参与校验/不进 content（投影正确）。"""
        summary_cls = _summary_model()
        anchors = _anchors(SCOPE_PROJECT, ["林晚", "低声道"])
        mock_llm.chat.return_value = _ok_response(
            project_specific=[_entry(content="叙述偏好：用角色全名而非代词", anchor_refs=["林晚"])],
            user_general=[_entry(content="编造的用户风格", anchor_refs=["证据外value"])],
        )
        summary, dropped = await summarizer.summarize(
            anchors, scope=SCOPE_PROJECT, project_id=PID, anchor_hash=ANCHOR_HASH, model=MODEL
        )
        assert isinstance(summary, summary_cls)
        assert dropped == 0  # user_general 的越界 anchor_refs 不参与防幻觉 B 校验
        assert summary.content == "叙述偏好：用角色全名而非代词"  # user_general 不进 content
        assert "编造的用户风格" not in summary.content
        assert mock_llm.chat.await_count == 1
