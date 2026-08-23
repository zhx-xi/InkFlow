"""F49 ② (#618) LLM 冲突判定管线 RED 契约测试 — PreferenceSupersedeDeterminer（全 mock LLM 轨）.

依据: .hermes/plans/task-618-contract.md §2（新管线 PreferenceSupersedeDeterminer 设计）/
§4（测试契约）/§5（memory_supersede 模板）；镜像 F45 M2
test_semantic_summarizer.py（mock LLM 形态: MagicMock(spec=LLMClientProtocol) +
chat=AsyncMock + mock_prompt_manager fixture + _payload/_ok_response helper）与
semantic_summarizer.py（_extract_json_fragment / _build_fix_prompt / _ParseOutcome /
修复式重试 ≤2 / 温度 0.2 / 防幻觉 B 骨架）。

RED 预期形态
------------
被测模块 inkflow.domain.services.preference_supersede_determiner 整体不存在 → 顶部
`from inkflow.domain.services import preference_supersede_determiner`（父包 from-import
形态——RED 期缺失模块直路径 import 会被 isort 判 third-party → I001，父包存在则
first-party 零 churn）→ 收集期 ImportError: cannot import name
'preference_supersede_determiner' from 'inkflow.domain.services'（等价 ModuleNotFoundError
收集错误，1 error，exit 2）。顶部仅此一个 F49 新符号 import；其余 F49 新符号
（SupersedeDeterminationError）一律用例体惰性 import——避免多缺失模块顶部 import 报
字母序首个导致 RED 根因漂移。GREEN 后全部可解析 → 14 用例全绿。

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
新建模块 inkflow.domain.services.preference_supersede_determiner（镜像 semantic_summarizer
骨架，不重造轮子）:

    class PreferenceSupersedeDeterminer:
        def __init__(self, *, llm_client, prompt_manager): ...   # ADR-015 Protocol 注入
        async def determine(self, new_value: str, anchors: list, *,
                            model: str) -> tuple[list[str], int]:
            # 返回 (superseded_values, dropped)
            # ① anchors 空 → ([], 0) 不调用 LLM
            # ② 渲染模板 memory_supersede（变量 {new_value}/{anchors}，
            #    anchors 传原始列表对象）→ ChatMessage 包装
            # ③ llm_client.chat(messages, model=model, temperature=0.2)
            # ④ _extract_json_fragment 提取 → json.loads → 校验顶层对象含
            #    "superseded" 为 str 列表——缺键/非 list/元素非 str → 重试
            # ⑤ 防幻觉 B: 每个 superseded value 必须 ∈ {a.value for a in anchors}，
            #    不在者丢弃（dropped+=1，不重试）
            # ⑥ 修复式重试 ≤2（共 3 次尝试）→ 仍失败 →
            #    SupersedeDeterminationError（inkflow.domain.ports.preference_supersede_errors）
        # 模块级 helper（同 F16/F45 命名）:
        #   _extract_json_fragment(text) -> str | None（镜像同款逻辑）
        #   _build_fix_prompt(error_detail) -> str（镜像 F16）
        #   _ParseOutcome 等价物（error/ok）

- 顶部 import 形态: `from inkflow.domain.services import preference_supersede_determiner`
  + 模块级别名 `PreferenceSupersedeDeterminer` = 模块同名属性（RED 收集错误根因唯一化；
    GREEN 后别名解析为类，测试体裸名引用镜像 F45）。
- SupersedeDeterminationError 位于 inkflow.domain.ports.preference_supersede_errors.py
  （镜像 semantic_summary_errors.py；本测试用例体惰性 import，仅断言异常类型，
  不约束构造参数语义）。
- 锚点 value 集合语义: 防幻觉 B 校验用锚点对象的 .value 字段集合
  （record_draft_edit 传入的既有 ProjectPreference，contract §3.2；determine 本身
  不感知 scope，本测试统一用项目级锚点构造）。
- 模板名 _TEMPLATE_NAME = "memory_supersede"；渲染变量 {new_value}（str）+
  {anchors}（原始列表对象，契约断言 render 收到原始对象）；渲染后消息经 ChatMessage 包装。
- LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。
- contract §3.2 的 MemoryService 接线（判定取代 → superseded_by / 降级审计 /
  注入排除）属 memory_service 编排层，不在本管线文件范围（另文件
  test_memory_supersede_wiring.py 覆盖）。

用例清单（全部 mock LLM，不调真实 API）:
1.  test_anchors_empty_returns_empty: anchors=[] → ([], 0)，chat 不被调用
2.  test_valid_json_returns_superseded_values: 合法 JSON → superseded 值列表
    （顺序保持）+ dropped==0
3.  test_fenced_json_extracted: ```json 围栏 + 前后缀文字包裹 → 提取成功
4.  test_invalid_json_retries_twice_then_raises: 3 次全非法 →
    SupersedeDeterminationError（await_count==3；第 2 次调用含 assistant+user 修复提示）
5.  test_invalid_json_recovers_on_retry: 首次非法二次合法 → 成功（await_count==2）
6.  test_missing_superseded_key_retries: 缺 superseded 键 → 重试后成功
7.  test_superseded_not_list_retries: superseded 非 list → 重试后成功
8.  test_superseded_element_not_str_retries: superseded 元素非 str → 重试后成功
9.  test_top_level_not_object_retries: 顶层 JSON 数组 → 重试后成功
10. test_hallucinated_value_dropped: 防幻觉 B: 锚点集外 value → 该条丢弃
    dropped==1，合法条保留
11. test_all_hallucinated_returns_empty_with_dropped: 全部越界 → ([], N) 静默丢弃不抛错
12. test_temperature_and_model_passed: llm.chat kwargs model/temperature==0.2 +
    模板渲染 {new_value}/{anchors} 原始列表对象注入（contract §2）
13. test_llm_request_error_propagates: LLMRequestError → 透传（await_count==1）
14. test_empty_superseded_list_returns_empty: {"superseded": []} → ([], 0)（判定无取代）

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
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services import preference_supersede_determiner

# 模块级别名: RED 期父包 from-import 收集错误 = ImportError: cannot import name
# 'preference_supersede_determiner' from 'inkflow.domain.services'（等价
# ModuleNotFoundError 收集错误，exit 2）；GREEN 后模块存在 → 别名解析为类，
# 测试体裸名引用镜像 F45。
PreferenceSupersedeDeterminer = preference_supersede_determiner.PreferenceSupersedeDeterminer

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
MODEL = "deepseek/deepseek-v4-flash"  # #415 唯一默认源，测试显式传入
TEMPLATE_NAME = "memory_supersede"
NEW_VALUE = "用「她」称呼主角"


def _payload(superseded: list | None = None) -> str:
    """构造合法 supersede 判定 JSON（{"superseded": [旧value, ...]}，contract §2）。"""
    return json.dumps(
        {"superseded": superseded if superseded is not None else ["低声道"]},
        ensure_ascii=False,
    )


def _ok_response(
    payload: str | None = None,
    *,
    superseded: list | None = None,
) -> ChatResponse:
    """构造 Mock LLM 成功响应（payload 或 superseded 关键字形态二选一）。"""
    if payload is None:
        payload = _payload(superseded=superseded)
    return ChatResponse(content=payload, model=MODEL)


def _anchor(value: str) -> ProjectPreference:
    """构造项目级锚点（record_draft_edit 传入的既有偏好，contract §3.2 输入）。"""
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


def _anchors(values: list[str]) -> list[ProjectPreference]:
    """按 value 列表构造锚点列表（determine 不感知 scope，统一项目级构造）。"""
    return [_anchor(v) for v in values]


pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM 客户端（chat 为 AsyncMock，镜像 F45 形态）。"""
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    """Mock Prompt 管理器（load 返回 memory_supersede 模板，render 返回渲染消息）。"""
    pm = MagicMock(spec=PromptTemplateProtocol)
    template = PromptTemplate(
        name=TEMPLATE_NAME,
        description="Preference supersede determination template",
        system_prompt="你是偏好取代判定器。输出严格 JSON。",
        human_prompt="新值：{new_value}\n锚点：\n{anchors}",
        variables=["new_value", "anchors"],
    )
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是偏好取代判定器。输出严格 JSON。"},
                {
                    "role": "user",
                    "content": (
                        "新值：用「她」称呼主角\n"
                        "锚点：\n- 低声道（style_word）\n- 林晚（style_word）"
                    ),
                },
            ],
            token_estimate=100,
        )
    )
    return pm


@pytest.fixture
def determiner(
    mock_llm: MagicMock, mock_prompt_manager: MagicMock
) -> PreferenceSupersedeDeterminer:
    """装配 PreferenceSupersedeDeterminer（Mock LLM + Mock PromptManager 注入，ADR-015）。"""
    return PreferenceSupersedeDeterminer(llm_client=mock_llm, prompt_manager=mock_prompt_manager)


class TestPreferenceSupersedeDeterminer:
    """LLM 冲突判定管线测试 — 解析 / 修复重试 / 防幻觉 B / 参数透传（全 mock LLM）。"""

    async def test_anchors_empty_returns_empty(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """① 锚点为空 → ([], 0)，不调用 LLM（contract §2）。"""
        result = await determiner.determine(NEW_VALUE, [], model=MODEL)
        assert result == ([], 0)
        mock_llm.chat.assert_not_awaited()

    async def test_valid_json_returns_superseded_values(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """②-⑤ 合法 JSON → superseded 值列表（顺序保持）+ dropped==0 + 单次调用。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.return_value = _ok_response(superseded=["低声道", "林晚"])
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道", "林晚"]
        assert dropped == 0
        assert mock_llm.chat.await_count == 1

    async def test_fenced_json_extracted(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④ 代码块围栏/前后缀文字包裹 → _extract_json_fragment 提取成功（镜像 F16）。"""
        anchors = _anchors(["低声道", "林晚"])
        fenced = f"好的，判定如下：\n```json\n{_payload()}\n```\n希望有帮助"
        mock_llm.chat.return_value = _ok_response(fenced)
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert dropped == 0

    async def test_invalid_json_retries_twice_then_raises(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④⑥ 输出完全非法 → 修复重试 2 次（共 3 次调用）→ SupersedeDeterminationError。"""
        from inkflow.domain.ports.preference_supersede_errors import SupersedeDeterminationError

        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response("还是不对"),
            _ok_response("依然失败"),
        ]
        with pytest.raises(SupersedeDeterminationError):
            await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert mock_llm.chat.await_count == 3  # 首次 + 2 次修复重试
        # 第 2 次调用携带修复 Prompt: assistant(原输出) + user(修复提示，附错误信息)
        call2_msgs = mock_llm.chat.await_args_list[1].args[0]
        assert call2_msgs[-2].role == "assistant"
        assert call2_msgs[-2].content == "这不是 JSON"
        assert call2_msgs[-1].role == "user"
        assert "JSON" in call2_msgs[-1].content

    async def test_invalid_json_recovers_on_retry(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④⑥ 非法输出后修复重试成功 → 返回判定（共 2 次调用）。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.side_effect = [
            _ok_response("这不是 JSON"),
            _ok_response(_payload()),
        ]
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert dropped == 0
        assert mock_llm.chat.await_count == 2

    async def test_missing_superseded_key_retries(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④ 输出缺 superseded 键 → 视为不可解析 → 修复重试后成功（共 2 次调用）。"""
        anchors = _anchors(["低声道", "林晚"])
        missing_key = json.dumps({"other": ["低声道"]}, ensure_ascii=False)
        mock_llm.chat.side_effect = [_ok_response(missing_key), _ok_response(_payload())]
        superseded, _ = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert mock_llm.chat.await_count == 2

    async def test_superseded_not_list_retries(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④ superseded 非 list（字符串）→ 结构校验失败 → 修复重试后成功。"""
        anchors = _anchors(["低声道", "林晚"])
        bad_payload = json.dumps({"superseded": "低声道"}, ensure_ascii=False)
        mock_llm.chat.side_effect = [_ok_response(bad_payload), _ok_response(_payload())]
        superseded, _ = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert mock_llm.chat.await_count == 2

    async def test_superseded_element_not_str_retries(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④ superseded 元素非 str（数字）→ 结构校验失败 → 修复重试后成功。"""
        anchors = _anchors(["低声道", "林晚"])
        bad_payload = json.dumps({"superseded": ["低声道", 123]}, ensure_ascii=False)
        mock_llm.chat.side_effect = [_ok_response(bad_payload), _ok_response(_payload())]
        superseded, _ = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert mock_llm.chat.await_count == 2

    async def test_top_level_not_object_retries(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④ 顶层 JSON 非对象（数组）→ 校验失败 → 修复重试后成功。"""
        anchors = _anchors(["低声道"])
        mock_llm.chat.side_effect = [
            _ok_response('["低声道"]'),
            _ok_response(_payload()),
        ]
        superseded, _ = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]
        assert mock_llm.chat.await_count == 2

    async def test_hallucinated_value_dropped(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """⑤ 防幻觉 B: superseded 含锚点集外 value → 该条丢弃（dropped+=1），
        合法条保留进返回列表（contract §2，宁少勿误）。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.return_value = _ok_response(superseded=["低声道", "比喻"])
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == ["低声道"]  # 仅锚点集内 value 保留
        assert dropped == 1
        assert "比喻" not in superseded
        assert mock_llm.chat.await_count == 1  # 丢弃不重试

    async def test_all_hallucinated_returns_empty_with_dropped(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """⑤ 全部 superseded value 越界 → ([], N) 静默丢弃不抛错（contract §2）。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.return_value = _ok_response(superseded=["比喻", "排比"])
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == []
        assert dropped == 2
        assert mock_llm.chat.await_count == 1

    async def test_temperature_and_model_passed(
        self,
        determiner: PreferenceSupersedeDeterminer,
        mock_llm: MagicMock,
        mock_prompt_manager: MagicMock,
    ) -> None:
        """②③ 模板渲染 {new_value}/{anchors} 注入 + llm.chat kwargs: model==传入 model、
        temperature==0.2；render 收到原始 anchors 列表对象（contract §2）。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.return_value = _ok_response(_payload())
        await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        kwargs = mock_llm.chat.await_args.kwargs
        assert kwargs["model"] == MODEL
        assert kwargs["temperature"] == 0.2
        # ② 模板渲染: memory_supersede 模板 + 变量 {new_value}/{anchors}（原始对象）
        mock_prompt_manager.load.assert_called_once_with(TEMPLATE_NAME)
        template = mock_prompt_manager.load.return_value
        mock_prompt_manager.render.assert_called_once_with(
            template, {"new_value": NEW_VALUE, "anchors": anchors}
        )

    async def test_llm_request_error_propagates(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """③ LLM 调用失败（LLMRequestError）→ 透传，不消耗解析重试（F16 §5.6 注同款）。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        with pytest.raises(LLMRequestError):
            await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert mock_llm.chat.await_count == 1

    async def test_empty_superseded_list_returns_empty(
        self, determiner: PreferenceSupersedeDeterminer, mock_llm: MagicMock
    ) -> None:
        """④⑤ 合法 JSON 但 superseded 为空列表（LLM 判定无取代）→ ([], 0)。"""
        anchors = _anchors(["低声道", "林晚"])
        mock_llm.chat.return_value = _ok_response(superseded=[])
        superseded, dropped = await determiner.determine(NEW_VALUE, anchors, model=MODEL)
        assert superseded == []
        assert dropped == 0
        assert mock_llm.chat.await_count == 1
