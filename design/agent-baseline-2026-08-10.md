# Agent 修改率基线报告（2026-08-10）

> **状态**：F27 交付时基线初始化（Q3 拍板：N=5/模式，2026-08-10）
> **用途**：F28 agent-memory 验收判据「修改率下降」的对照值（spec f27 §5.6 / §13 M8）
> **数据源**：drafts 表 status/confirmed_at + confirm 时内容 diff + audit_logs（severity_summary 承载动作语义）

## 测量口径（spec §5.6）

对每章记录三个指标：
1. **直接确认**：生成后用户直接 confirm（0 修改）→ 修改率 0%
2. **手动修改字数 diff**：确认前用户手动编辑的字符数差（草稿 vs 确认写入内容）
3. **重新生成率**：reject 后重新生成的章节数 / 总章节数

## 基线数据

| 模式 | 章节数 | 直接确认 | 平均修改 diff | 修改率均值 | 重新生成率 | 备注 |
|------|--------|----------|---------------|------------|------------|------|
| deterministic | 5 | 待填 | 待填 | 待填 | 待填 | F27 静态链基线 |
| agentic | 5 | 待填 | 待填 | 待填 | 待填 | F27 ReAct 基线 |

> ⚠️ **数据采集说明**：F27 交付时仅建立测量机制（confirm 时 diff 字数落 audit），
> N=5/模式 的实际运行数据随日常使用积累（spec §14 Q3 拍板：
> 「基线测量随开发自然积累，不强制一次性跑完」）。本表为 F28 验收时的对照入口。

## 测量机制落地（F27 交付内容）

1. **drafts 表**：status（draft/confirmed/rejected）+ confirmed_at —— 确认/拒绝流留痕
2. **audit_logs**：`severity_summary = draft_confirmed/draft_rejected/auto_saved/draft_saved`
   + summary 含字数（草稿保存 N 字）——F28 diff 事件源
3. **agent_run 表**：steps JSON 快照（决策轨迹全量）+ token_usage_total —— 成本与行为对照

## F27 冒烟记录（2026-08-10）

- 真实模型冒烟（zhipu/glm-4.5，INKFLOW_ZHIPU_API_KEY）：1 章 agentic 运行，**PASS 10/10**
  - run status=completed / terminated_by=llm（自然终止，未触发护栏）
  - 决策轨迹 2 步（工具调用 + 正文输出）、正文 111 字（min_words 为提示性引导）
  - 草稿自动落库（draft 状态）、审计日志 3 行（draft_saved/auto_saved/run_completed）
  - 冒烟暴露并修复：deepagents 0.7.5 invoke 需 `{"messages": [...]}` dict（InvalidUpdateError）
    + graph.invoke 为同步方法（TypeError await）——装配层 DeepAgentInvokeAdapter 双修复
- 冒烟结论：**agentic 闭环（ReAct 循环 → 正文 → 草稿 → 审计 → 决策轨迹）真实可用**

## 与 F28 的关系

F28 交付 `inkflow memory stats` 类命令时，本表数据作为「修改率下降」判据的
对照基线；F27 只建测量不做统计 UI（spec §10 不在范围内）。
