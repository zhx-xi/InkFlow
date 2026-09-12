"""F60 首启模型就绪判据单元测试（#934 §2.1/§9.1 + #1129 多源收敛）。

被测：`inkflow.domain.services.model_readiness` —
    - `compute_readiness`（纯函数，零 I/O）：判定「是否已具备可解析 chat 模型 + 有效 key」
    - `is_chat_model_resolvable`（#1129 唯一可解析谓词）：readiness 与下拉/写作链共用

判据（#1129 收敛后，唯一真相）：存在**可解析的 chat 模型**——三级数据源任一命中：
    (1) 注册表某 provider ∈ 已存 key 集合 且 models[] 含 type == "chat"（#934 既有语义）
    (2) project.config.model 可解析（provider 有可用 key 且非注册表确知 embedding）
    (3) config.llm_default_model 可解析（同上）

> #1129 根因：写作链真实可用性由 `resolve_model(None, project_model, global_default)` 判定
> （api/_llm_resolver.py:37），而旧判据只查 models[]。`provider_config_service.create` 的
> 「自动设全局默认」只写内存单例 + config.json（:226-233），**从不回写注册表 models[]**
> → 「已存 key + 默认模型可解析」的合法路径判据恒 false → GUI 引导锁死且无出路。

契约来源：specs/f60-first-run-guide/spec.md §2.1 / §3.1 / §9.1；issue #1129。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.domain.services.model_readiness import compute_readiness

# ---------------------------------------------------------------------------
# 构造器：仅填判据相关字段（id/时间戳与判据无关）
# ---------------------------------------------------------------------------


def _pc(
    name: str,
    models: list[ProviderModel],
    *,
    default_model: str | None = None,
) -> ProviderConfig:
    """构造一个 ProviderConfig（判据只读 name + models[].type + default_model）。"""
    return ProviderConfig(id=1, name=name, default_model=default_model, models=models)


def _chat(model_id: str = "gpt-4o") -> ProviderModel:
    return ProviderModel(id=model_id, type="chat")


def _embedding(model_id: str = "embedding-3") -> ProviderModel:
    return ProviderModel(id=model_id, type="embedding")


# ---------------------------------------------------------------------------
# 空注册表 → no_provider（N1 真·全新安装）
# ---------------------------------------------------------------------------


def test_empty_registry_not_ready_no_provider() -> None:
    """空注册表 → ready=False, reason='no_provider'（真·全新安装）。"""
    result = compute_readiness([], set())
    assert result.ready is False
    assert result.reason == "no_provider"
    assert result.has_chat_model is False
    assert result.has_embedding_model is False


def test_provider_registered_without_key_still_no_key() -> None:
    """有 provider 含 chat 模型但无 key → no_key（#821 空 key 守卫语义）。"""
    result = compute_readiness([_pc("openai", [_chat()])], set())
    assert result.ready is False
    assert result.reason == "no_key"
    assert result.has_chat_model is False  # 无 key 不算「可用 chat 模型」


# ---------------------------------------------------------------------------
# #929 精确缺陷形态：只有 embedding 模型（有 key）→ 必须不 ready
# ---------------------------------------------------------------------------


def test_only_embedding_model_with_key_not_ready_929_regression() -> None:
    """#929 回归锚：唯一 provider 只配 embedding 模型 + 有 key → ready=False。

    这是 zhipu embedding-3 被当 chat 装配的精确配置形态——判据必须显式筛 type。
    """
    result = compute_readiness([_pc("zhipu", [_embedding("embedding-3")])], {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_chat_model"
    assert result.has_chat_model is False
    assert result.has_embedding_model is True  # embedding 侧仍可见（RAG 可用）


# ---------------------------------------------------------------------------
# 就绪正路径
# ---------------------------------------------------------------------------


def test_chat_model_with_key_is_ready() -> None:
    """有 chat 模型 + key → ready=True, reason='ready'。"""
    result = compute_readiness([_pc("deepseek", [_chat("deepseek-chat")])], {"deepseek"})
    assert result.ready is True
    assert result.reason == "ready"
    assert result.has_chat_model is True


def test_ready_implies_reason_ready() -> None:
    """ready=True ⟺ reason='ready'（不变量，GUI 按 reason 定位起始步骤）。"""
    result = compute_readiness([_pc("openai", [_chat()])], {"openai"})
    assert result.ready is (result.reason == "ready")


# ---------------------------------------------------------------------------
# 多 provider 混合：存在即就绪
# ---------------------------------------------------------------------------


def test_mixed_providers_one_complete_is_ready() -> None:
    """多 provider 混合——只要一个满足全部条件即就绪。"""
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 但只 embedding
        _pc("openai", [_chat()]),  # 无 key
        _pc("deepseek", [_chat("deepseek-chat")]),  # 有 key + chat ← 这条兜住
    ]
    result = compute_readiness(providers, {"zhipu", "deepseek"})
    assert result.ready is True
    assert result.reason == "ready"


def test_key_on_wrong_provider_does_not_help() -> None:
    """key 与 chat 模型必须在同一 provider 上才算就绪（跨 provider 不串用）。"""
    providers = [
        _pc("openai", [_chat()]),  # 有 chat 无 key
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_key"


# ---------------------------------------------------------------------------
# has_embedding_model 独立判定
# ---------------------------------------------------------------------------


def test_has_embedding_model_independent_of_chat() -> None:
    """embedding 存在性与 chat 就绪性彼此独立（N2 / RAG 置灰判据）。"""
    # 有 chat + key（就绪），但无 embedding
    ready_no_embed = compute_readiness([_pc("deepseek", [_chat()])], {"deepseek"})
    assert ready_no_embed.ready is True
    assert ready_no_embed.has_embedding_model is False

    # 有 chat + embedding + key
    with_embed = compute_readiness(
        [_pc("deepseek", [_chat("deepseek-chat"), _embedding("embed-1")])],
        {"deepseek"},
    )
    assert with_embed.ready is True
    assert with_embed.has_embedding_model is True


def test_embedding_model_without_key_not_counted() -> None:
    """embedding 无 key → has_embedding_model=False（同 key_saved 语义）。"""
    result = compute_readiness([_pc("zhipu", [_embedding()])], set())
    assert result.has_embedding_model is False


# ---------------------------------------------------------------------------
# 防御：provider 无模型条目
# ---------------------------------------------------------------------------


def test_provider_with_no_models_not_ready() -> None:
    """provider 已注册 + 有 key 但 models 为空 → no_chat_model（防御）。"""
    result = compute_readiness([_pc("openai", [])], {"openai"})
    assert result.ready is False
    assert result.reason == "no_chat_model"


# ---------------------------------------------------------------------------
# reason 优先级：no_provider > no_chat_model > no_key
# ---------------------------------------------------------------------------


def test_reason_priority_no_chat_model_over_no_key() -> None:
    """reason 优先级：注册表**全无** chat 模型（不论 key）→ no_chat_model。

    语义：用户连模型都没配齐时，先引导配模型（步骤 1），而非先补 key。
    反例见下方 test_reason_priority_no_key_when_chat_exists_elsewhere。
    """
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
        _pc("openai", [_embedding("text-embedding-3")]),  # 无 key 也无 chat
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.reason == "no_chat_model"


def test_reason_priority_no_key_when_chat_exists_elsewhere() -> None:
    """注册表**存在** chat 模型（但该 provider 无 key）→ no_key（不是 no_chat_model）。

    no_chat_model 判据 = 全注册表无任何 chat 条目，与 key 无关；只要某处
    配了 chat 模型，缺的是 key → 引导补 key。
    """
    providers = [
        _pc("zhipu", [_embedding()]),  # 有 key 无 chat
        _pc("openai", [_chat()]),  # 有 chat 无 key ← 决定 reason
    ]
    result = compute_readiness(providers, {"zhipu"})
    assert result.ready is False
    assert result.reason == "no_key"


# ═══════════════════════════════════════════════════════════════════════════
# #1129：多源判据收敛 —— 可解析 chat 模型三级数据源
# ═══════════════════════════════════════════════════════════════════════════


def test_project_model_resolvable_with_key_is_ready_1129() -> None:
    """场景 1（#1129 阻断形态）：仅 project.config.model 配了可解析 chat 模型，
    注册表 models[] 为空（只 llm set-key）→ ready=True。

    旧判据下恒 false（models[] 无 chat 条目）→ GUI 引导页锁死。这是 issue 实证场景。
    """
    providers = [_pc("deepseek", [], default_model="deepseek/deepseek-v4-flash")]
    result = compute_readiness(
        providers, {"deepseek"}, project_models=["deepseek/deepseek-v4-flash"]
    )
    assert result.ready is True
    assert result.has_chat_model is True
    assert result.reason == "ready"


def test_global_default_model_resolvable_with_key_is_ready_1129() -> None:
    """场景 2：仅 settings.default.model（config.llm_default_model）→ ready=True。

    同一 src，落点不同：`inkflow config set default.model` 或
    `provider_config_service.create` 的 #735 D2 自动设默认，都不写 models[]。
    """
    providers = [_pc("deepseek", [], default_model="deepseek/deepseek-v4-flash")]
    result = compute_readiness(
        providers,
        {"deepseek"},
        global_default="deepseek/deepseek-v4-flash",
    )
    assert result.ready is True
    assert result.reason == "ready"


def test_registry_chat_entry_is_ready_1129() -> None:
    """场景 3：注册表 models[type=chat] 有条目 + key → ready=True（#934 既有语义不回归）。"""
    providers = [_pc("deepseek", [_chat("deepseek-v4-flash")])]
    result = compute_readiness(
        providers,
        {"deepseek"},
        global_default="deepseek/deepseek-v4-flash",
    )
    assert result.ready is True
    assert result.has_chat_model is True
    assert result.reason == "ready"


def test_only_embedding_registry_with_default_model_still_no_chat_model_1129() -> None:
    """场景 4（反例守护）：真无任何可用 chat（只有 embedding），
    且 project/global 默认**未配置** → ready=False, reason='no_chat_model'（#929 形态保留）。
    """
    providers = [_pc("zhipu", [_embedding("embedding-3")])]
    result = compute_readiness(providers, {"zhipu"})
    assert result.ready is False
    assert result.has_chat_model is False
    assert result.reason == "no_chat_model"


def test_builtin_env_provider_resolvable_without_saved_key_1129() -> None:
    """场景 4b：provider 无已存 key，但 key 来自内置 env 源（#1129 第 4 级
    `_BUILTIN_PROVIDERS`，含 ollama 占位）→ 可解析。真实部署形态（.env / 进程 env）。
    """
    result = compute_readiness(
        [],
        set(),
        global_default="ollama/qwen2.5",
        builtin_providers={"ollama": "ollama"},
    )
    assert result.ready is True
    assert result.has_chat_model is True


def test_embedding_model_as_project_model_not_ready_1129() -> None:
    """场景 5：zhipu 仅 embedding-3 被配成 project.config.model → **不得**判为 chat 就绪。

    注册表确知 type=embedding（#936 B 项同源判据，`_lookup_registry_model_type`
    镜像：无该条目/查询异常 → 放行）→ 该源视为不可用 → 不得因「有个模型名」就放行。
    否则 #929 的 embedding 误装配通道会从 readiness 侧重新打开。
    """
    providers = [_pc("zhipu", [_embedding("embedding-3")])]
    result = compute_readiness(
        providers,
        {"zhipu"},
        project_models=["zhipu/embedding-3"],
    )
    assert result.ready is False
    assert result.has_chat_model is False  # 不得被 embedding 名号顶成可用 chat
    assert result.has_embedding_model is True


def test_resolvable_model_without_key_not_ready_1129() -> None:
    """反例守护：project/global 有模型名但该 provider **无任何 key 来源** → no_key。

    「可解析」= 模型名可解析 **且** 凭据可用（与 resolve_llm_credentials 同真相）。
    """
    providers = [_pc("deepseek", [], default_model="deepseek/deepseek-v4-flash")]
    result = compute_readiness(providers, set(), project_models=["deepseek/deepseek-v4-flash"])
    assert result.ready is False
    assert result.reason == "no_key"


def test_unknown_model_not_registry_listed_is_resolvable_1129() -> None:
    """误伤防御：模型名在注册表**未登记**（未知 ≠ embedding）→ 放行。

    镜像 `_llm_resolver._lookup_registry_model_type`：查不到条目绝不阻断主路径；
    用户手填任意 chat 模型名（第三方 OpenAI 兼容端点）必须可用。
    """
    providers = [_pc("deepseek", [], default_model="deepseek/deepseek-v4-flash")]
    result = compute_readiness(
        providers, {"deepseek"}, project_models=["deepseek/deepseek-v4-flash"]
    )
    assert result.ready is True


# ── 唯一可解析谓词（P3：readiness 与下拉/写作链共用） ──


def test_is_chat_model_resolvable_shared_predicate() -> None:
    """#1129 P3：`is_chat_model_resolvable` 是唯一可解析谓词——
    readiness 与下拉数据源共用，禁第二份判定逻辑。
    """
    from inkflow.domain.services.model_readiness import is_chat_model_resolvable

    providers = [_pc("zhipu", [_embedding("embedding-3")])]
    assert is_chat_model_resolvable("zhipu/glm-4.5", providers, {"zhipu"}, builtin_providers={})
    assert not is_chat_model_resolvable(
        "zhipu/embedding-3", providers, {"zhipu"}, builtin_providers={}
    )
    assert not is_chat_model_resolvable("zhipu/glm-4.5", providers, set(), builtin_providers={})
    assert not is_chat_model_resolvable("", providers, {"zhipu"}, builtin_providers={})
    assert not is_chat_model_resolvable(None, providers, {"zhipu"}, builtin_providers={})


def test_is_chat_model_resolvable_rejects_malformed_forms() -> None:
    """谓词边界：无斜杠 / 空 provider 段 / 空模型段 → 一律 False（不误判为可用）。"""
    from inkflow.domain.services.model_readiness import is_chat_model_resolvable

    providers = [_pc("deepseek", [_chat("dm")])]
    saved = {"deepseek"}
    assert not is_chat_model_resolvable("no-slash", providers, saved, builtin_providers={})
    assert not is_chat_model_resolvable("/dm", providers, saved, builtin_providers={})
    assert not is_chat_model_resolvable("deepseek/", providers, saved, builtin_providers={})
    assert not is_chat_model_resolvable("deepseek/   ", providers, saved, builtin_providers={})


def test_registry_model_type_skips_other_providers() -> None:
    """注册表查 type：遍历跳过非目标 provider；目标 provider 无该条目 → None（放行）。"""
    from inkflow.domain.services.model_readiness import is_chat_model_resolvable

    providers = [
        _pc("openai", [_embedding("text-embedding-3-small")]),
        _pc("deepseek", [_chat("dm")]),
    ]
    saved = {"openai", "deepseek"}
    # 目标 provider 在列表后段（必须先 skip 掉 openai 才命中 deepseek）
    assert is_chat_model_resolvable("deepseek/dm", providers, saved, builtin_providers={})
    # 目标 provider 无该条目 → None ≠ "embedding" → 放行
    assert is_chat_model_resolvable("deepseek/unknown", providers, saved, builtin_providers={})


# ── 装配 helper 的降级分支（单源失败绝不阻断主路径） ──


def test_read_builtin_providers_returns_mapping() -> None:
    """read_builtin_providers 正常返回 dict（含 ollama 占位）。"""
    from inkflow.domain.services.model_readiness import read_builtin_providers

    builtin = read_builtin_providers()
    assert isinstance(builtin, dict)
    assert builtin.get("ollama")


def test_read_builtin_providers_degrades_on_import_error() -> None:
    """内置 provider 表导入失败 → {}（不冒泡。镜像 _llm_resolver 误伤防御）。"""
    import sys

    from inkflow.domain.services.model_readiness import read_builtin_providers

    module = "inkflow.infrastructure.llm.provider_config"
    saved_module = sys.modules.get(module)
    sys.modules[module] = None  # type: ignore[assignment]  # 触发 ImportError
    try:
        assert read_builtin_providers() == {}
    finally:
        if saved_module is not None:
            sys.modules[module] = saved_module
        else:
            sys.modules.pop(module, None)


def test_read_global_default_returns_string() -> None:
    """_read_global_default 正常返回字符串（空配置 → ""）。"""
    from inkflow.domain.services.model_readiness import _read_global_default

    assert isinstance(_read_global_default(), str)


@pytest.mark.asyncio
async def test_read_project_models_degrades_on_db_error() -> None:
    """项目表读取失败 → []（端点 helper 绝不冒泡；镜像 read_builtin_providers）。"""
    from inkflow.domain.services.model_readiness import read_project_models

    class _Boom:
        async def scalars(self, *_args, **_kwargs):
            raise RuntimeError("db boom")

    assert await read_project_models(_Boom()) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_read_project_models_extracts_only_valid_model_values() -> None:
    """项目模型抽取：非 dict / 无 model 键 / 非字符串 / 空白 → 跳过；合法值保留。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from inkflow.domain.services.model_readiness import read_project_models
    from inkflow.infrastructure.database.models.project import ProjectORM

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ProjectORM.metadata.create_all) if hasattr(
            ProjectORM, "metadata"
        ) else None
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(ProjectORM(name="valid", config={"model": "deepseek/dm"}))
        session.add(ProjectORM(name="blank", config={"model": "   "}))
        session.add(ProjectORM(name="no-model", config={}))
        session.add(ProjectORM(name="not-str", config={"model": 123}))
        await session.commit()
        models = await read_project_models(session)
    await engine.dispose()
    assert models == ["deepseek/dm"]
