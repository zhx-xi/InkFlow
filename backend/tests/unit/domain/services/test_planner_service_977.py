"""#977 planner LLM 静默回退修复契约测试（TDD RED 阶段）。

权威来源：contract-977.md §0 根因表 / §1 PlannerService 契约 / §4 RED-1 轨。
本文件为 `domain/services/planner_service.py`（MODIFY）的 #977 RED-1 轨契约定义。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【构造扩展】PlannerService 新增两个关键字参数（默认值向后兼容，§1）：
   - project_repo: 鸭子对象（async .get(int) -> Project | None，None = 未装配）
   - llm_default_model: str = config.llm_default_model（镜像 character_service.py:94）

2. 【动态提问解析段】（§1，_generate_questions 在 llm_client is None 早退之后、
   重试循环之前插入）：
   - 经 project_repo.get(session.project_id.int) 取项目 config.model；
   - resolve_model(None, project_model, llm_default_model) 单点收口；
   - 两级皆空 → 一次 loguru WARNING「未配置默认模型，访谈使用模板题库」
     + 不调 chat + return None → 模板兜底；
   - chat 调用点显式传 model=model（重试循环内每次均带）。

3. 【行为矩阵】（§1，start/respond 共用 _generate_questions）：
   - llm_client=None（未装配）→ 不调 chat、return None（无 WARN）
   - 项目 config.model 非空 → 调 chat，model=项目模型（即使全局为空，不 WARN）
   - 无项目模型 + 全局非空 → 调 chat，model=全局默认（#735 回退语义）
   - 两级皆空 → 不调 chat + 一次 WARN + return None → 模板兜底，零 ERROR traceback
   - chat 运行期异常 → 调（带 model）重试 1 次 → None 兜底（场景 15 既有语义不变）
   - project_repo.get 抛异常 → 视为无项目模型，回退全局（访谈不因项目查询崩）

4. 【RED 预期形态】当前实现 _generate_questions 不传 model 且构造无
   llm_default_model/project_repo 参数 → 本文件 5 个【R】用例
   TypeError（unexpected keyword 'llm_default_model'/'project_repo'）；
   【G】用例（llm_client=None 语义区分守护）现即绿。

环境隔离条款（§6）：本机进程 env / instance.env 可能注入真实 llm_default_model
——所有依赖模型判别/空的用例一律显式构造 llm_default_model，禁止依赖 config 实际值。
"""

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    PlannerService,
)

_MUST_ANSWER_KEYS = ("题材", "篇幅", "主题")
"""通用必答项 key（服务端强约束，§6 R11 ①；_llm_json 默认出全量避免重试）。"""


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _make_repo() -> AsyncMock:
    """planner 会话 repo 鸭子对象（planner_session / writing_plan 存取桩）。"""
    repo = AsyncMock()
    repo.get_planner_session.return_value = None
    repo.get_writing_plan.return_value = None
    return repo


def _llm_json(
    questions: list | None = None,
    confirmed_items: list | None = None,
    conflicts: list | None = None,
) -> str:
    """构造 LLM 结构化 JSON 输出字符串（§5.1 prompt 输出形状）。

    默认 questions 含 3 个通用必答项（题材/篇幅/主题），保证 start 不触发
    「缺失必答项→重试」，使 chat 恰好调用一次、await_args 语义干净。
    """
    if questions is None:
        questions = [
            {
                "id": "q1",
                "text": "题材：悬疑为主还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
                "kind": "general",
            },
            {
                "id": "q2",
                "text": "篇幅：预计多少字？",
                "template": "约 ___ 字",
                "kind": "general",
            },
            {
                "id": "q3",
                "text": "主题：能否一句话描述主题？",
                "template": "主题是 ___",
                "kind": "general",
            },
        ]
    return json.dumps(
        {
            "questions": questions or [],
            "confirmed_items": confirmed_items or [],
            "conflicts": conflicts or [],
        },
        ensure_ascii=False,
    )


def _make_llm_client(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.chat.return_value = ChatResponse(content=content, model="test")
    return llm


def _outline_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _char_dummy() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _make_project_repo(project_model: str | None) -> AsyncMock:
    """fake project_repo：get 返回带 config.model 的鸭子对象（或 None=无项目行）。"""
    project_repo = AsyncMock()
    if project_model is None:
        project_repo.get.return_value = None
    else:
        project_repo.get.return_value = SimpleNamespace(config=ProjectConfig(model=project_model))
    return project_repo


def _make_service(
    repo: AsyncMock,
    *,
    llm_client: AsyncMock | None = None,
    project_context_getter: AsyncMock | None = None,
    prompt_manager: AsyncMock | None = None,
    project_repo: AsyncMock | None = None,
    llm_default_model: str = "test/model",
) -> PlannerService:
    """#977 装配：默认注入 llm_client + 项目模型通道（llm_default_model 默认非空）。"""
    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=AsyncMock(return_value=_char_dummy()),
        llm_client=llm_client,
        project_context_getter=project_context_getter
        or AsyncMock(return_value="设定摘要：时间旅者，悬疑基调"),
        prompt_manager=prompt_manager,
        project_repo=project_repo,
        llm_default_model=llm_default_model,
    )


@contextmanager
def _capture_loguru(level: str = "WARNING"):
    """loguru sink 捕获（镜像 test_log.py logger.add/remove 形态）：记录 ≥ level 的消息。

    收到的是 loguru `Message`（str 子类），经 `.record['level'].name` /
    `.record['message']` 读取级别与格式化文本——本文件所有 WARN 断言均以此为凭。
    """
    records = []
    sink_id = logger.add(lambda message: records.append(message), level=level)
    try:
        yield records
    finally:
        logger.remove(sink_id)


def _warning_records(records) -> list:
    return [r for r in records if r.record["level"].name == "WARNING"]


def _error_records(records) -> list:
    return [r for r in records if r.record["level"].name == "ERROR"]


# ── 契约 §4 RED-1 轨：model 透传 + 空链 WARN ──────────────────────


@pytest.mark.asyncio
async def test_generate_questions_passes_project_model():
    """【R】项目 config.model 非空 → chat 调用带 model=项目模型（§4 RED-1 用例 1）。

    锁 model 传递：当前 _generate_questions 不传 model 且无 project_repo 通道，
    chat.await_args.kwargs 无 'model' 键 → AssertionError。
    """
    repo = _make_repo()
    llm = _make_llm_client(_llm_json())
    project_repo = _make_project_repo("deepseek/deepseek-v4-flash")
    svc = _make_service(repo, llm_client=llm, project_repo=project_repo)

    await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    call = llm.chat.await_args
    assert call is not None
    assert call.kwargs["model"] == "deepseek/deepseek-v4-flash"


@pytest.mark.asyncio
async def test_project_model_wins_over_global():
    """【R】项目模型 + 构造 llm_default_model='' → chat model=项目模型，零 WARN（§4 RED-1 用例 2）。

    项目模型优先于全局（即使全局空），不报错、不降级。
    """
    repo = _make_repo()
    llm = _make_llm_client(_llm_json())
    project_repo = _make_project_repo("project/model")
    svc = _make_service(repo, llm_client=llm, project_repo=project_repo, llm_default_model="")

    with _capture_loguru("WARNING") as records:
        await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    call = llm.chat.await_args
    assert call is not None
    assert call.kwargs["model"] == "project/model"
    assert _warning_records(records) == []


@pytest.mark.asyncio
async def test_fallback_to_global_when_no_project():
    """【R】无项目行（get→None）+ 全局非空 → chat model=全局，零 WARN（§4 RED-1 用例 3）。

    无项目行（或 config.model=None）→ 回退全局默认模型（#735 回退语义）。
    """
    repo = _make_repo()
    llm = _make_llm_client(_llm_json())
    project_repo = _make_project_repo(None)
    svc = _make_service(
        repo,
        llm_client=llm,
        project_repo=project_repo,
        llm_default_model="global/model",
    )

    with _capture_loguru("WARNING") as records:
        await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    call = llm.chat.await_args
    assert call is not None
    assert call.kwargs["model"] == "global/model"
    assert _warning_records(records) == []


@pytest.mark.asyncio
async def test_both_empty_warns_once_no_chat_no_error():
    """【R】两级皆空 → 不调 chat + 恰好一次 WARN（含模板文案）+ 零 ERROR（§4 RED-1 用例 4）。

    空默认模型时不得产生 24 条 ERROR traceback；一次 WARN 且 return None → 模板兜底。
    """
    repo = _make_repo()
    llm = _make_llm_client(_llm_json())
    svc = _make_service(repo, llm_client=llm, project_repo=None, llm_default_model="")

    with _capture_loguru("WARNING") as records:
        session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    llm.chat.assert_not_awaited()
    warns = _warning_records(records)
    assert len(warns) == 1
    assert "未配置默认模型，访谈使用模板题库" in warns[0].record["message"]
    assert _error_records(records) == []
    # 两级皆空 → 模板题库兜底（§0 背景：静默回退模板题库）
    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]


@pytest.mark.asyncio
async def test_project_repo_exception_falls_back_to_global():
    """【R】project_repo.get 抛异常 → 视为无项目模型，回退全局（不崩、WARN 0 条）。

    访谈不因项目查询崩溃；异常吞掉后走全局默认模型。
    """
    repo = _make_repo()
    llm = _make_llm_client(_llm_json())
    project_repo = AsyncMock()
    project_repo.get.side_effect = RuntimeError("db down")
    svc = _make_service(
        repo,
        llm_client=llm,
        project_repo=project_repo,
        llm_default_model="global/model",
    )

    with _capture_loguru("WARNING") as records:
        await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    call = llm.chat.await_args
    assert call is not None
    assert call.kwargs["model"] == "global/model"
    assert _warning_records(records) == []


@pytest.mark.asyncio
async def test_llm_client_none_no_warn():
    """【G】llm_client=None（未装配）→ 确定性兜底、chat 不调、零 WARN（§4 RED-1 用例 6）。

    未装配 ≠ 未配置：llm_client=None 在 _generate_questions 早退（不触 model 解析），
    直接模板兜底，且不产生 WARN（语义区分守护，现即绿）。
    """
    repo = _make_repo()
    svc = PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=_outline_dummy()),
        character_service=AsyncMock(return_value=_char_dummy()),
    )

    with _capture_loguru("WARNING") as records:
        session = await svc.start(_pid(), "写一本关于时间旅者的悬疑小说")

    assert [q["id"] for q in session.asked_questions] == [q["id"] for q in ROUND1_QUESTIONS]
    assert _warning_records(records) == []
