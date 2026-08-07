# F87: LangGraph 管线状态重构（StateGraph(dict) → TypedDict + reducer）

**Spec 版本**: 1.0
**对应 Issue**: [#87](https://github.com/zhx-xi/InkFlow/issues/87)
**里程碑**: 0.3.1（质量加固补丁）
**类型**: 内部重构（无新用户功能，行为不变）
**分支**: `feat/f87-langgraph-refactor`
**依据**: AGENTS.md §5.1（spec 是唯一真相来源）· ADR-015（LangChain 全家桶，本重构不改变技术选型）· inkflow-dev `references/langchain-langgraph-stack.md` §6.2（方案已实测）
**状态**: ✅ 已实现（PR #110）

## 1. 概述

将 LangGraph Agent 管线的状态管理从 `StateGraph(dict)` 反模式重构为 TypedDict + 嵌套 results dict + reducer：节点只返回增量（partial updates），动态 stage key 收进嵌套 `results` dict。**外部行为（`AgentPipelineProtocol.execute/validate` 契约）完全不变**，仅内部状态表示与节点返回语义变更。

## 2. 背景与问题

2026-08-03 LangGraph 1.x 代码审查（inkflow-dev §6.2 实测）确认：

1. **整体替换语义**：`StateGraph(dict)` 下节点返回的 dict 会**整体替换** state（连初始输入的 key 都会丢失）→ 当前代码被迫让每个节点原地 mutate + 返回完整 state（`pipeline_nodes.py` L57-59 注释准确描述了这一约束）。
2. **全量复制**：每个 super-step 都复制 `context`/`stages`/`llm_client`，无谓开销。
3. **无类型安全**：state 是裸 `dict`，`langgraph_pipeline.py` 有 3 处 `type: ignore[type-var]`（L113×2、L115）+ 1 处 `type: ignore[attr-defined]`（L158）。
4. **并行定时炸弹**：注释声明「并行执行属 Phase 2」——一旦 Phase 2 并行，两个节点同时返回完整 dict 必然互相覆盖（last-write-wins），且丢失彼此写入。

## 3. 目标状态设计（已实测跑通，inkflow-dev §6.2）

### 3.1 PipelineState TypedDict

```python
class PipelineState(TypedDict):
    context: PipelineContext
    stages: dict[str, PipelineStage]
    llm_client: LLMClientProtocol
    _abort: NotRequired[bool]
    results: Annotated[dict[str, StageResult], operator.or_]  # 动态 stage key 收进嵌套 dict
```

- 动态 stage key（`{stage_id}_output/_status/...`）无法静态表达 → 用嵌套 `results: dict[str, StageResult]` 承载，`Annotated[..., operator.or_]` 声明合并 reducer。
- `_abort` 保持普通字段（覆盖语义）：节点**只置 True、从不置 False**，last-write-wins 安全（任一节点置 True 后全局生效，后续节点读到即跳过）。

### 3.2 节点增量返回（pipeline_nodes.py）

节点只返回增量，不再 mutate + 返回完整 state：

```python
async def architect_node(state: PipelineState) -> dict:
    return {"results": {stage_id: StageResult(...)}}   # 只返回增量

# 失败路径额外带 _abort：
return {"_abort": True, "results": {stage_id: StageResult(status=FAILED, ...)}}
```

各返回路径的 `results` 内容（与现状逐字段等价）：

| 路径 | results 内容 |
|------|-------------|
| 成功（第 N 次尝试） | `StageResult(stage_id, COMPLETED, output=响应, retry_count=N-1)` |
| 重试耗尽 required | `_abort: True` + `StageResult(stage_id, FAILED, error=最后错误, retry_count=max_retries)` |
| 重试耗尽非 required | `StageResult(stage_id, SKIPPED, error=最后错误, retry_count=max_retries)` |
| 上游已 abort（跳过） | `StageResult(stage_id, SKIPPED)`（不调用 LLM，output/error 为空） |

- `_build_messages` 读取上游输出改为 `state["results"][key].output`（与旧 `state.get(f"{key}_output", "")` 等价：skipped 上游的 StageResult.output 默认 `""`）。
- 节点函数签名 `state: PipelineState`，返回 `dict`（LangGraph 接受 TypedDict partial）。

### 3.3 execute 汇总逻辑（langgraph_pipeline.py）

- `workflow = StateGraph(PipelineState)`，消除全部 `type: ignore[type-var]`。
- 结果汇总从 `results` dict 读：

```python
stage_results = [
    final_state["results"].get(
        stage.id,
        StageResult(stage_id=stage.id, status=StageStatus.COMPLETED),
    )
    for stage in stages
]
```

`.get` 默认 COMPLETED 与旧 `final_state.get(f"{stage_id}_status", StageStatus.COMPLETED.value)` 语义等价（线性链中每个节点必被执行，results 均已有记录，默认值仅防御）。

- `final_output` 从 `final_state["results"][terminal.id].output` 读。
- **PipelineError.result 类型声明**：`domain/ports/agent_pipeline.py` 的 `PipelineError` 增加类属性 `result: PipelineResult | None = None`（纯类型声明，零运行时行为变化，向后兼容），消除 `type: ignore[attr-defined]`（L158）。

## 4. 行为不变约束（黑盒契约）

重构前后 `LangGraphAgentPipeline.execute()` / `validate()` 的**外部可观察行为必须逐项一致**（由既有测试锁定）：

1. 顺序执行：architect → writer → auditor → reviser 线性链、调用顺序、model/temperature 透传
2. 输出传递：下游收到上游输出（`{architect_output}` 等变量渲染、user 消息拼接格式不变）
3. validate：空图 / 重复 id / 多入口 / 多终点 / 非法上游引用 / 环检测，错误文案不变
4. 重试：max_retries 语义、retry_count 值不变
5. 跳过：required=False 失败 → skipped 下游继续；required=True 失败 → 下游全 skipped、LLM 调用计数不变
6. 失败传播：`PipelineError` 抛出时机、消息文案（含阶段 id）、`error.result` 携带的 PipelineResult 内容不变
7. 结果汇总字段：`status`/`output`/`error`/`retry_count` 逐字段等价（skipped 阶段 output="" 不变）

## 5. 文件变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` | MODIFY | 节点改为增量返回，删除原地 mutate 与全量返回 |
| `backend/src/inkflow/infrastructure/agent/langgraph_pipeline.py` | MODIFY | PipelineState 定义 + StateGraph(PipelineState) + results 汇总 + 消除 type: ignore |
| `backend/src/inkflow/domain/ports/agent_pipeline.py` | MODIFY | PipelineError 加 `result: PipelineResult \| None = None` 类属性（纯类型声明） |
| `backend/tests/unit/test_pipeline_nodes.py` | **NEW** | 节点增量契约测试（RED 载体） |
| `backend/tests/unit/test_langgraph_pipeline.py` | 不改 | 既有黑盒契约测试，行为不变基线 |
| `specs/f87-langgraph-refactor/spec.md` | NEW | 本 spec（同 PR 合入） |

## 6. 测试策略

### 6.1 既有测试（行为不变基线）

`backend/tests/unit/test_langgraph_pipeline.py` 10 个测试**一字不改**：全部经 `execute()` 黑盒断言，重构前后都必须全绿——它们是行为不变的证明。

### 6.2 新增节点契约测试（RED 载体）

`backend/tests/unit/test_pipeline_nodes.py`（新建，unit 目录自动进 CI）：

| 用例 | 断言 |
|------|------|
| 正常节点返回增量 | 直接调用 `architect_node(state)` → 返回值**只含 `results` 键**（不含 `context`/`stages`/`llm_client`）；`results[stage_id].output/status` 正确 |
| 失败路径 | 重试耗尽 required → 返回含 `_abort: True` + `results[stage_id]` FAILED + retry_count=max_retries |
| abort 跳过路径 | `_abort` 已置 → 返回 `results[stage_id]` SKIPPED，**不调用 LLM** |
| 并行合并语义 | 两个节点增量 dict 的 `results` 经 `operator.or_` 合并后两 stage key 并存（锁并行安全前提） |

### 6.3 RED 形态

当前实现（节点返回完整 state）下，新测试断言「只含 results 键」必然失败（返回值含 context/stages/llm_client）→ **AssertionError 类失败**（非收集期错误），同时既有 10 个测试保持全绿。

## 7. 验收标准

1. **测试先行（F15 规矩）**：先写新测试并确认 RED FAIL（新测试失败、既有测试全绿），再实现
2. `pytest backend/tests/unit/test_langgraph_pipeline.py backend/tests/unit/test_pipeline_nodes.py` 全绿
3. `langgraph_pipeline.py` / `pipeline_nodes.py` 中无 `type: ignore`（0 处）
4. 行为不变：§4 全部 7 项由既有黑盒测试证明（重构前后同绿）
5. 不做 Phase 2 并行（本 Issue 只做状态机制重构，并行留待后续）
6. 全量回归：backend 单元 + 顶层集成/CLI 测试全绿（CI 等价命令）

## 8. 不在范围

- Phase 2 并行执行（节点并发）
- LangGraph RetryPolicy 替换手写重试（inkflow-dev §6.4：业务语义是状态机，仍需节点内处理）
- langchain-community sunset 迁移（§6.3，单独 ADR 记录）
- 新增/修改任何用户可见 API、CLI、配置

## 9. 依赖关系

- ADR-015：LangChain 全家桶选型（本重构遵守，不引入新依赖）
- inkflow-dev §6.2：方案已实测（TypedDict + reducer 跑通）
- 无跨模块行为依赖；`domain/ports/agent_pipeline.py` 仅类型声明改动，向后兼容
