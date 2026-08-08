# F34: CLI 恒经 HTTP 路由改造（cli_http）— 功能规格（骨架）

> **Spec 版本**: 0.1（骨架草稿） | **日期**: 2026-08-09 | **依据**: ADR-030 ② D1=A（CLI 恒经 HTTP）、ADR-021（内核并发契约）、F30 spec（ensure_kernel 消费方）、Constitution P1-P6
>
> **所属阶段**: 0.6.0（估算 3-4 人天，含既有 CLI 测试改造）
>
> **关联 Issues**: #169（本模块）；#166（F30 ensure_kernel，✅ 已实现 PR #171）；#168（CLI 产物，✅ 已实现 PR #181）
>
> **依赖**: ✅ F30（ensure_kernel + kernel.json 契约）· ✅ F33（CLI 独立产物，spawn 定位复用）· ✅ F7（CLI 全局约定：JSON 信封/退出码/错误码）
>
> **参考 ADR**: [ADR-030](../../adr/ADR-030.md)（② D1=A 恒经 HTTP）· [ADR-021](../../adr/ADR-021.md)（内核交付契约）· [ADR-019](../../adr/ADR-019.md)（版本里程碑）
>
> **状态**: 待实现 🔲（0.6.0）
>
> > ⚠️ **本文件为骨架草稿**：随 #169 评估结论落盘（2026-08-09，独立 spec 不并入 f30）。完整 13 节在评审后补齐——当前仅锁定定位、边界与关键决策，正文各节留占位。

---

## 1. 概述（骨架）

### 1.1 模块类型定位（候选：第 15 变体「CLI 传输层改造型」）

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
| 核心机制 | ✅ CLI 顶层 ensure_kernel 接线 + HTTP 客户端层（`infrastructure/http/`）+ 错误映射（HTTP 状态 → F7 错误码） |
| 跨模块 MODIFY | ✅ 全部既有 CLI 命令文件（`cli/commands/*.py`）调用路径改造 |
| 错误面 | CLI 错误码/信封不变；新增内核拉起失败路径（KernelStartupError → CLI 明确报错） |

### 1.2 边界声明（骨架）

- **不做**：内核生命周期管理（F30 已交付）；CLI 打包（F33 已交付）；MCP 薄客户端（F20，1.0.0）
- **不变**：JSON 信封契约、退出码、错误码（F7 契约冻结）；CLI 命令签名与参数
- **变**：数据来源（domain 直连 → HTTP）、import 面（全量 → httpx 轻量）

---

## 2-13. 待补齐（骨架占位）

| 节 | 内容要点（评审时展开） |
|----|------------------------|
| §2 数据模型 | 无新实体；HTTP 客户端配置（base_url/token 来源 kernel.json） |
| §3 API 契约 | 消费既有端点清单（F1-F24 全部）；SSE 流式消费（F23） |
| §4 CLI 签名 | 命令签名零变化；顶层接线位置（app.py entrypoint） |
| §5 关键差异 | ensure_kernel 接线时序；httpx 客户端生命周期；错误映射表（HTTP → F7 错误码）；流式转发 |
| §6 组织规则 | 客户端层依赖注入；token 传递；日志 |
| §7 边界与错误 | 内核未运行/拉起失败/超时/HTTP 5xx/SSE 中断 |
| §8 文件结构 | CREATE `infrastructure/http/`；MODIFY 全部 `cli/commands/*.py` + `cli/app.py` + 测试 |
| §9 测试策略 | 既有 27 个 CLI 测试文件改造（mock httpx vs 真实内核两轨）；热调用延迟 ≤100ms 验证 |
| §10 不在范围 | 内核生命周期/MCP/打包 |
| §11 依赖关系 | F30/F33/F7；被依赖：无（消费方末端） |
| §12 决策记录 | HTTP 客户端层位置（infrastructure/http vs cli 内）；测试策略（MockTransport vs 真实内核） |
| §13 验收标准 | M1-M5 映射 issue #169 验收（信封一致/自动拉起/错误映射/既有 CLI 测试通过/延迟 ≤100ms） |

---

## 待澄清问题（骨架，≥2 个）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | HTTP 客户端层放哪？`infrastructure/http/`（跨 CLI/MCP/skills 复用）vs `cli/` 内私有模块？ | 影响 F20 MCP 薄客户端复用面 | A：infrastructure/http/（MCP 1.0.0 直接复用） |
| Q2 | 既有 CLI 测试改造策略？mock httpx（快、隔离）vs 起真实内核集成（真、慢）？ | 影响 27 个测试文件的改造量与 CI 时长 | A：双轨——单元 mock + 少量真实内核集成（M5） |

---

*本文件为 F34 骨架（评估结论载体），完整版随评审推进补齐。*
