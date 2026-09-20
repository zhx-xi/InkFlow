# Contract-929：LLM 模型装配 fail-fast 化 + model_routing provider 键值化 + 向量层空串守卫

> 用户拍板（2026-09-05，替代原「A 确定性降级」单一方案）：
> ① `model_routing` 改 provider 键 → `{model, type}` 值对象（value 用**裸模型名**，不带 provider/ 前缀；消费侧拼 LiteLLM 格式）；
> ② **删除最终 fallback**（不再遍历注册表取 models[0]）——解析不到模型 → **日志输出装配诊断 + fail-fast 422**，绝不静默装配；
> ③ 首启用户引导 = 独立 issue **#934**（milestone 0.14.0），不进本 PR；
> ④ 向量层空串守卫（原拍板 A）保留（#929 issue 修复方向 1，家族根治）。

## §0 根因表（复现终裁，探针 C 实证 D:\tmp\929-repro2）

| # | 缺陷 | 位置（origin/main 8d6c5f7） | 实证 |
|---|------|---------------------------|------|
| R1 | 空默认回退取 `models[0]` 不筛 type → zhipu `embedding-3`（type=embedding）被装配为 chat 模型 → ChatOpenAI 打 chat completions → zhipu 400 1213「未正常接收到prompt参数」 | `api/_llm_resolver.py:41-53`、`api/deps_chat_agent.py:95-107`（内联副本同缺陷） | CHAT PROBE = 同款 1213；progress_reason 逐字匹配；日志 start_run→build_agentic_writer→invoke failed（121ms，无 embed 调用痕迹） |
| R2 | `model_routing` 键错位：task 键（writing/audit/…）被 provider 名查询 → 永远 miss → #415「生成默认 deepseek」在回退链失效 | `core/config.py:179-184` 定义 × `provider_config.py:213,222` 消费 | 静态实锤 |
| R3 | book 轨 writer 无视项目模型（项目已配 `deepseek/deepseek-v4-flash`），直传全局空默认 | `api/routers/books.py:263` | rc2 DB projects.config.model 实证 |
| R4 | 向量层 `_index_sync:196/_index_batch_sync:217/_retrieve_sync:242` 空串无守卫（#328 只修维度探测点）→ 空白输入直打 zhipu 400 | `infrastructure/rag/langchain_vector_store.py` | EMPTY EMBED PROBE = 同款 1213（家族风险确认） |

## §1 新数据结构（core/config.py + domain/models/provider_config.py）

```python
# domain/models/provider_config.py 新增（与 ProviderModel 并列）
class ProviderDefault(BaseModel):
    """model_routing 值对象：provider 内置默认模型（模型名不带 provider/ 前缀）。"""
    model: str
    type: Literal["chat", "embedding"] = "chat"

# core/config.py 替换 model_routing（原 4 个 task 键废止——用户拍板：provider 为键）
model_routing: dict[str, ProviderDefault] = {
    "openai": ProviderDefault(model="gpt-4o", type="chat"),
    "deepseek": ProviderDefault(model="deepseek-v4-flash", type="chat"),
    "zhipu": ProviderDefault(model="glm-4.5", type="chat"),
}
```
- 值来源 = `cli/commands/llm.py:21-26 _PROVIDER_MODELS` 实见值（ollama 无内置默认 → 不入表；audit/outline 的 task 粒度路由废止，一律 provider 级默认）。
- `cli/commands/llm.py` `_PROVIDER_MODELS` **删除**，`llm list` 改读 `config.model_routing`（单一默认源，#415 原则；缺键显示 "unknown" 语义保留）。

## §2 get_provider_config 消费（provider_config.py:213,222）

```python
def _builtin_default_model(provider: str) -> str:
    """内置路由默认（chat 型才可为 chat 消费）→ LiteLLM 格式 provider/model；无 → ""。"""
    entry = config.model_routing.get(provider)
    if entry is None or entry.type != "chat":
        return ""
    return f"{provider}/{entry.model}"
```
- L213 改：`default_model = registry_entry.default_model or _builtin_default_model(provider) or config.llm_default_model`
- L222 改：`default_model = _builtin_default_model(provider) or config.llm_default_model`
- `LLMProviderConfig` 形状**不变**（models 仍 list[str]——resolver 不再消费它，最小变更，勿动 schema）。

## §3 resolve_llm_credentials 重做（api/_llm_resolver.py）

```python
def resolve_llm_credentials(
    global_default: str,
    *,
    project_model: str | None = None,
) -> tuple[str, str, str]:
    """解析 (model, api_key, base_url)：project_model > global_default；无解 → 日志诊断 + 422。

    不再遍历注册表回退（#929 拍板：删除最终 fallback）。
    """
    model = resolve_model(None, project_model, global_default) or ""
    if not model:
        logger.error(
            "LLM 模型解析失败（未配置）: project_model={} global_default={} "
            "内置路由={}（可 config set default.model provider/model 或项目设置）",
            project_model or "-", global_default or "-", sorted(config.model_routing),
        )
        raise HTTPException(422, detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型")
    try:
        provider, _ = parse_model_string(model)
        provider_cfg = get_provider_config(provider)
    except ValueError as exc:
        logger.error(
            "LLM 模型解析失败（provider key 不可用）: model={} 原因={}",
            model, exc,
        )
        raise HTTPException(422, detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型") from exc
    return model, provider_cfg.api_key, provider_cfg.base_url or ""
```
- **422 detail 文案 = 现状逐字保留**（`未配置默认模型，请在设置中配置 LLM Provider 和默认模型`，#821 契约兼容）。
- 诊断日志关键字 = `LLM 模型解析失败`（测试断言锚，loguru `{}` 格式）。
- 签名向后兼容：既有单参调用点零改动可编译。

## §4 调用点收敛/扩展

| 调用点 | 变更 |
|--------|------|
| `api/deps_chat_agent.py:83-112` | 删除内联复制（含遍历回退），函数级 `from inkflow.api._llm_resolver import resolve_llm_credentials` → `model, api_key, base_url = resolve_llm_credentials(config.llm_default_model)`；后续消费变量名不变 |
| `api/routers/books.py:_writer_factory` | `cfg = await _project_config_getter(expected_project_id) if expected_project_id else None` → `resolve_llm_credentials(config.llm_default_model, project_model=getattr(cfg, "model", None))`（**per-delegate 解析**；装配期 L263 顶层 resolve 删除） |
| `api/deps.py get_agentic_writer_service` | 单参调用不动（签名兼容）；其装配期 resolve 保留（deps 路径无项目上下文注入点，#821 同源） |

## §5 向量层空串守卫（infrastructure/rag/langchain_vector_store.py）

| 点位 | 语义 |
|------|------|
| `_retrieve_sync` 入口 | `query.strip()` 为空 → `logger.warning`（含 project_id）+ **return []**（不调 embed_query、不打 chroma，锁外） |
| `_index_sync` | `entity.content.strip()` 为空 → warning（含实体 id/type）+ **no-op return**（不写 chroma；reindex 差集口径一致——该 id 不在库） |
| `_index_batch_sync` | 分组内过滤空白 content（逐条 warning 记录被跳过 oid）；过滤后组为空 → continue；embed_documents 入参**恒不含空白串** |

- 守卫 = 确定性降级：不阻断调用方（reindex 继续、retrieve 返回空结果集），符合用户「降级不中断」原则。
- 服务层/编排层**不加**守卫（单点在 store 层，防发散）。
- 空白判定统一 `not text or not text.strip()`（None 防御含）。

## §5b 契约修订（2026-09-05 父侧设计收口，与 §4 配合）

- `_writer_factory` 内部**直接 await `_project_config_getter(expected_project_id)`** 读项目模型（镜像 `_resolve_merged_limits` L4 先例；不扩 BookService 构造参数——#897 旧装配鸭子形态零破坏）。
- `start_run` 入口**无条件预检**（保 #860「无凭据 → POST /runs 422 优先于 404」语义）：prepare_run 之前 → `plan = await svc._repo.get_writing_plan(id)`（异常/None → project_model=None 继续预检，404 判定仍归 prepare_run）→ `cfg = await svc._project_config_getter(plan.project_id) if plan else None` → `resolve_llm_credentials(config.llm_default_model, project_model=getattr(cfg, "model", None))`；抛 HTTPException 原样透传（422）。预检在 prepare_run 改状态**之前**——拒绝零残留。既有 `test_book_key_resolution_860.py` 契约 3 的 `side_effect=_raise_no_key(_default)` 需加 `**kw` 签名兼容（迁移表，父侧已改）。
- `_build_book_service` 装配期**不再调 resolve**（顶层 L263 删除）——凭据解析全部延迟到委托/预检（修 R3 + #738 假象：装配期只有全局模型可用）。

## §6 既有测试迁移（父侧已完成 2026-09-05，Codex 禁改 tests/）

**#738/#758 契约反转留痕**：`test_deps_chat_agent_model_resolution.py` / `test_deps_agentic_model_resolution.py` 的
「空默认模型 → 注册表回退首个有 key provider」契约（D3=A）**被本拍板②取代**——空默认 → 422（fail-fast，
不再扫描回退）；「全 provider 无 key → 422」用例语义不变保留。

| 文件 | 迁移状态 |
|------|----------|
| `test_llm_resolver.py` 契约 2 | ✅ 翻转为 422-without-scanning |
| `test_config.py` model_routing 默认值 | ✅ provider 键 + ProviderDefault |
| `test_provider_config.py` TestModelRoutingAuditFix | ✅ provider 键断言 |
| `test_provider_config_resolution.py:188` | ✅ `f"deepseek/{entry.model}"` |
| `test_book_key_resolution_860.py` 契约 1/3 | ✅ 委托时机断言 + `**kw` 兼容 |
| `test_deps_chat_agent_model_resolution.py` | ✅ fail-fast 反转（scan_count==0 锚） |
| `test_deps_agentic_model_resolution.py` | ✅ 同上 |
| `test_deps_chat_agent_coverage_gaps.py` | ✅ 3 回退弧用例改判 422 |

**RED 判据实测（父侧 2026-09-05，隔离 INKFLOW_DATA_DIR）**：11 文件 = 28 failed（17 新【R】+ 11 迁移契约红）/ 32 passed。
GREEN 完成判据 = **同批 60 用例全绿** + 全量零回归。

## §7 Codex 允许修改的 src 白名单

1. `backend/src/inkflow/domain/models/provider_config.py`（+ProviderDefault）
2. `backend/src/inkflow/core/config.py`（model_routing 新结构）
3. `backend/src/inkflow/infrastructure/llm/provider_config.py`（_builtin_default_model + L213/222）
4. `backend/src/inkflow/api/_llm_resolver.py`（§3 重做）
5. `backend/src/inkflow/api/deps_chat_agent.py`（§4 收敛）
6. `backend/src/inkflow/api/routers/books.py`（§4/§5b）
7. `backend/src/inkflow/infrastructure/rag/langchain_vector_store.py`（§5）
8. `backend/src/inkflow/cli/commands/llm.py`（_PROVIDER_MODELS 删除改读 config）
9. `adr/llm/ADR-049.md`（新建，§9）+ `adr/README.md`（索引登记）
10. `specs/f14-extraction/spec.md` / `specs/f19-gui/spec.md` / `specs/f44-book-orchestrator/spec.md`（§10 定点修订）

**禁改**：`tests/`、`backend/tests/`、契约文件、ci.yml、前端。禁 `# pragma`、禁新增 fallback 变体。

## §8 范围外（勿动，父侧另行处理）

- `infrastructure/context/sources.py` 检索装配空 query 源头排查：本批探针证实 book 链路无 retrieve 调用点，暂不改；
- `PUT /vector/embedding-model` 的 CLI 命令缺口 → 另行；
- 首启引导 → #934（0.14.0）；
- 服务层 `ExtractionService.retrieve` 双路径（自愈重试）不改语义。

## §9 ADR-049（adr/llm/ADR-049.md，状态=已接受）

标题：LLM 模型装配 fail-fast 化——删除静默回退，provider 键内置路由，诊断日志先行。
背景=#929 复现链（R1-R4）；决策=§1-§5；备选=①仅 type 过滤保留回退（否决：静默挑模型仍可能挑错场景，用户拍板删除）②空 query 抛错阻断（否决：降级不中断原则）；影响=「只配 embedding 无 chat」环境从假可用变显式 422+日志；#821 打包版回退语义废止，由 #934 首启引导承接流程面。登记 `adr/README.md` 索引。

## §10 spec 修订（同 PR）

- `specs/f14-extraction/spec.md`：§5.6/§7 边界表新增「空白 query / 空白 content 实体 → 确定性降级（warn + 跳过/空结果）」+ 修订履历；
- `specs/f19-gui/spec.md`：provider 解析节（§8.2②/§10 决策表）#821 回退语义 → fail-fast 语义；
- `specs/f44-book-orchestrator/spec.md`：#860 凭据节 → per-delegate 项目模型解析（R3）。
- 原则：spec 以本契约合入后的实现为准改写（用户先例：spec 对齐已合入实现）。
