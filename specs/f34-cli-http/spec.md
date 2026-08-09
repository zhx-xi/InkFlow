# F34: CLI 恒经 HTTP 路由改造（cli_http）— 功能规格（骨架）

> **Spec 版本**: 0.2（骨架草稿 v0.2） | **日期**: 2026-08-09 | **依据**: ADR-030 ② D1=A（CLI 恒经 HTTP）、ADR-021（内核并发契约）、F30 spec（ensure_kernel 消费方）、Constitution P1-P6
>
> **Spec 变更**（0.1 → 0.2）：Q1-Q2 已拍板（2026-08-09 用户选 A/A）——Q1=HTTP 客户端层放 `infrastructure/http/`（供 F20 MCP 复用）；Q2=测试双轨（mock httpx 主轨 + 少量真实内核集成）。**变体编号修正（评审 S4）**：本模块为 **第 16 变体「CLI 传输层改造型」**（f36=第 15 变体，编号不冲突）；**零 cli 依赖约束（评审 S8）**：http/ 层不 import cli 任何模块（MCP 复用前提）；M 行明细补齐（评审 🔴-3）。
>
> **所属阶段**: 0.6.0（估算 3-4 人天 → 评审复核建议 **4-5 人天**，含既有 CLI 测试改造）
>
> **关联 Issues**: #169（本模块）；#166（F30 ensure_kernel，✅ 已实现 PR #171）；#168（CLI 产物，✅ 已实现 PR #181）
>
> **依赖**: ✅ F30（ensure_kernel + kernel.json 契约）· ✅ F33（CLI 独立产物，spawn 定位复用）· ✅ F7（CLI 全局约定：JSON 信封/退出码/错误码）
>
> **参考 ADR**: [ADR-030](../../adr/ADR-030.md)（② D1=A 恒经 HTTP）· [ADR-021](../../adr/ADR-021.md)（内核交付契约）· [ADR-019](../../adr/ADR-019.md)（版本里程碑）
>
> **状态**: 待实现 🔲（0.6.0）
>
> > ⚠️ **本文件为骨架草稿**：随 #169 评估结论落盘（2026-08-09，独立 spec 不并入 f30）。完整 13 节在评审后补齐——当前已锁定定位、边界、Q1-Q2 拍板、M 行明细与关键决策，正文业务节（§2-§7）留占位。

---

## 1. 概述（骨架）

### 1.1 模块类型定位（第 16 变体「CLI 传输层改造型」）

F34 是 ADR-030 ② D1=A 的消费方改造：**所有 `inkflow <cmd>` 先 `ensure_kernel()` 再经 HTTP 调用内核**，移除 CLI 直连 domain 的隐含双路径（ADR-030 已拍板，非本 spec 决策点）。

```
现状:  inkflow <cmd> → 直连 domain（asyncio.run + repo/service 全量 import，~4.7s 冷启动）
改造:  inkflow <cmd> → ensure_kernel() → httpx → http://127.0.0.1:{port}/api/v1/...（~214ms 热调用）
       输出契约不变（F7 JSON 信封 / 退出码 0/1/2 / 错误码）
```

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无 |
| 新 API 端点 | ❌ 无（消费既有全部端点，含 F23 SSE） |
| 新 CLI 命令 | ❌ 无（改造既有命令的调用路径） |
| 核心机制 | ✅ CLI 顶层 ensure_kernel 接线 + HTTP 客户端层（`infrastructure/http/`，Q1=A）+ 错误映射（HTTP 状态 → F7 错误码） |
| 跨模块 MODIFY | ✅ 全部既有 CLI 命令文件（`cli/commands/*.py`）调用路径改造 + 全部 27 个 CLI 测试文件（tests/cli/，分布 5 个 ci.yml job） |
| 错误面 | CLI 错误码/信封不变；新增内核拉起失败路径（KernelStartupError → CLI 明确报错） |

### 1.2 边界声明（骨架）

- **不做**：内核生命周期管理（F30 已交付）；CLI 打包（F33 已交付）；MCP 薄客户端（F20，1.0.0）
- **不变**：JSON 信封契约、退出码、错误码（F7 契约冻结）；CLI 命令签名与参数
- **变**：数据来源（domain 直连 → HTTP）、import 面（全量 → httpx 轻量）
- **⚠️ 零 cli 依赖约束（评审 S8）**：`infrastructure/http/` 必须是**纯基础设施层，不 import `cli/` 任何模块**——否则 F20 MCP 复用即形成反向依赖（MCP 引用 CLI 层）。此约束写入 §6 组织规则（骨架占位）。

---

## 2-7. 待补齐（骨架占位）

| 节 | 内容要点（评审时展开） |
|----|------------------------|
| §2 数据模型 | 无新实体；HTTP 客户端配置（base_url/token 来源 kernel.json） |
| §3 API 契约 | 消费既有端点清单（F1-F24 全部）；SSE 流式消费（F23） |
| §4 CLI 签名 | 命令签名零变化；顶层接线位置（app.py entrypoint） |
| §5 关键差异 | ensure_kernel 接线时序；httpx 客户端生命周期；错误映射表（HTTP → F7 错误码）；流式转发；**错误码缺口（评审 🟡-4）：HTTP 500 无法区分 LLM_ERROR/DB_ERROR（API 只有 detail 文本）→ 需补「API 错误响应契约扩展」（detail 结构 `{code, message}` 或错误头）或 CLI 侧按 detail 文本匹配（脆弱，不推荐）** |
| §6 组织规则 | 客户端层依赖注入；token 传递；日志；**零 cli 依赖约束（S8）** |
| §7 边界与错误 | 内核未运行/拉起失败/超时/HTTP 5xx/SSE 中断 |

---

## 8. 文件结构（骨架草案，评审 S8 细化）

```text
backend/src/inkflow/
├── infrastructure/
│   ├── kernel/                       ← F30 既有（拉起+状态：ensure_kernel/KernelHandle/kernel.json）
│   └── http/                         ← CREATE: 传输层（Q1=A）
│       ├── __init__.py               ← CREATE: 导出 InkFlowHTTPClient / HttpErrorMapper
│       ├── client.py                 ← CREATE: httpx.AsyncClient 封装（base_url/token 头/超时/SSE 流式支持）
│       └── errors.py                 ← CREATE: HTTP 状态 → F7 错误码映射
├── cli/
│   ├── app.py                        ← MODIFY: 顶层 ensure_kernel 接线（entrypoint）
│   └── commands/*.py                 ← MODIFY: 19 个命令文件调用路径改 HTTP（数据源替换，签名不变）
backend/tests/
├── unit/test_http_client.py          ← CREATE: mock httpx 轨（自动覆盖，无需改 ci.yml）
└── cli/
    ├── test_cli_*.py（27 文件）       ← MODIFY: mock httpx 轨改造（分布 5 个 job）
    └── test_cli_http_kernel.py       ← CREATE: 真实内核轨（M5；并入 integration-cli-backend 或并入 test_cli_kernel.py）
```

> 依赖方向：`cli/commands/* → http/ → (只读消费) kernel state`，kernel 不依赖 http；http/ 不依赖 cli（S8）。

---

## 9. 测试策略（骨架，Q2=A 双轨）

```text
mock 轨（主轨，自动覆盖）:  test_http_client.py（base_url/token 注入、错误映射表、SSE 流式转发 mock）
                           + 27 个既有 CLI 测试文件改造（mock httpx，快/稳/隔离）
真实内核轨（少量）:        test_cli_http_kernel.py（M5：无内核 → ensure_kernel 拉起 → 调用成功；
                           显式加入 ci.yml integration-cli-backend job——该 job 已有 test_cli_kernel.py
                           真实内核 fixture 先例；备选：并入 test_cli_kernel.py 零 ci.yml 改动）
延迟验证:                  热调用 ≤100ms 手工基准脚本（不入常规 CI——环境抖动会假红）
```

> **⚠️ CI 落点（QA 评审 🟡-6）**：mock 轨自动覆盖（unit-backend + coverage-backend 目录收集）；真实内核轨**必须显式加入 ci.yml**（Windows pytest 不展开 glob，Issue #59/#61 教训）。

---

## 10-12. 待补齐（骨架占位）

| 节 | 内容要点 |
|----|----------|
| §10 不在范围 | 内核生命周期/MCP/打包 |
| §11 依赖关系 | F30/F33/F7；被依赖：无（消费方末端） |
| §12 决策记录 | **已固化**：D1=infrastructure/http/（Q1=A，MCP 复用 + 分层正确性）；D2=双轨测试（Q2=A）；D3=零 cli 依赖（S8）；D4=错误码缺口设计待定（🟡-4） |

---

## 13. 验收标准（骨架，M 行明细已补齐——评审 🔴-3）

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | HTTP 客户端层（`infrastructure/http/`） | `pytest backend/tests/unit/test_http_client.py -v` 全绿（base_url/token 注入、错误映射表、SSE 流式转发、零 cli import 断言） |
| M2 | 顶层 ensure_kernel 接线 | mock 轨：CLI 命令改造后既有测试全绿（27 文件 × 5 job 逐个验证）；真实轨：M5 |
| M3 | 错误映射（HTTP 状态 → F7 错误码） | unit 测试全绿（404→NOT_FOUND、422→VALIDATION_ERROR、内核拉起失败→KernelStartupError、超时/5xx） |
| M4 | 既有 CLI 测试改造 | 27 个既有 CLI 测试文件全绿（mock 轨；分布 5 个 job 逐个验证） |
| M5 | 真实内核集成 + 热调用延迟 | `tests/cli/test_cli_http_kernel.py`（或并入 test_cli_kernel.py）全绿 + **显式加入 ci.yml integration-cli-backend**；延迟 ≤100ms 手工基准验证（不入 CI） |
| M6 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #169 验收标准映射：信封一致 = M1/M4；自动拉起 = M5；错误码/退出码映射 = M3；既有 CLI 测试通过 = M4；热调用 ≤100ms = M5。

---

## 待澄清问题（骨架，已拍板 2 个）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | HTTP 客户端层放哪？`infrastructure/http/`（跨 CLI/MCP/skills 复用）vs `cli/` 内私有模块？ | 影响 F20 MCP 薄客户端复用面 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**infrastructure/http/**（§8/§12 D1） |
| Q2 | 既有 CLI 测试改造策略？mock httpx（快、隔离）vs 起真实内核集成（真、慢）？ | 影响 27 个测试文件的改造量与 CI 时长 | ✅ 已确认（2026-08-09 拍板：**选项 A**）——**双轨：单元 mock + 少量真实内核集成（M5）**（§9/§12 D2） |

---

*本文件为 F34 骨架（评估结论载体 + Q1-Q2 拍板 + M 行明细），完整版（§2-§7/§10-§11 正文）随评审推进补齐。*
