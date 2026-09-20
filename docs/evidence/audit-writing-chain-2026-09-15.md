# 四路交叉审计：写作链「设定注入」与「审计闭环」缺陷族

> 本文件是本次审计的**权威汇总**（2026-09-15，父侧 + 4 子 agent 交叉验证）。
> 建 issue 时逐条引用本文件对应小节。

## 审计方法（证据强度说明）

四路独立角色审计 + 父侧逐条复核（不采信子 agent 自报）：

| 路 | 角色 | 独有贡献 |
|---|---|---|
| 1 | 规格合规审计员 | spec 要求逐条提取（S1-1..S1-15 / S2-1..S2-6）；发现 **F44 §11 spec 谎报** |
| 2 | 真实用户视角验证员 | 作者痛感场景化（S1..S7）；发现**同卷并行互不知情**、**全书无字数约束** |
| 3 | 架构一致性评审员 | 轨迹对照表（**6 条写入轨 / 5 套 prompt / 3 套审计 / 2 个 factory**）；F58 授权漏接 |
| 4 | 测试盲区审计员 | **恒真同源断言**（`test_book_service.py:646-647`）；门禁结构性失效分析 |
| 父 | 架构师（我） | 独立取证并复核全部关键结论；发现 `chapter.writing_requirements` 零消费 |

**四路在两条最严重缺陷上完全一致**（审计不读正文 / 写作零 F6 注入）→ 可信度最高。

---

## 轨迹全图（架构一致性路产出，父侧复核）

| # | 轨 | 入口 | prompt 来源 | 审计来源 | 上下文来源 |
|---|---|---|---|---|---|
| T1 | F27 单章 agentic | `deps_agentic_writer.py:41` | `writer_agent.yaml` + `_build_initial_message`(user 消息) | 工具 `audit_chapter` → F34 | 调用方传参；**无 F6** |
| T2 | F44 静态书级 | `books.py:513` mode=static | `book_service.py:866`（复制品#1） | **无** | 占位符；**无 F6** |
| T3 | F44 卷级 | `books.py:513` mode=volume | `book_pipeline.py:537`（复制品#2） | **无** | 占位符；**无 F6** |
| T4 | F49 书级自主 | `books.py:513` mode=agentic | `book_agentic_pipeline.py:814`（复制品#3） | `_delegate_audit`(L829-863) 独立实现 | 占位符；**无 F6** |
| T5 | F42 多 agent 管线 | `books.py:120` | `i18n/prompts/zh/*.yaml` + Agent 实体 | 管线 `auditor` 节点 | 自造 `_assemble_setting_context`；**无 F6** |
| T6 | chat agent | `deps_chat_agent.py:82` | `pipeline_templates.py:112` + F6 渲染 | 工具 `audit_chapter` → F34 | **唯一 F6 消费者** |

**`_writer_factory` 共享面**：`books.py:324` 一个实例注入 T2/T3/T4 三条轨（改一处影响三条）；T1 的 `deps_agentic_writer.py:79` 是**独立实现**，与前者零代码共享。

---

## P0 缺陷（4 条）

### P0-1 · 审计不读正文（最严重）
`book_agentic_pipeline.py:830-848`：system 说「请审校章节**正文**」，user 实给 `chapter['name'] + chapter['description']`（**大纲描述**）。写出的稿存 `drafts` 表，审计**从不读**。
- 证据：`:836-848`、`:447 _find_chapter`（返回大纲节点 dict，无 content 键）、`:794-801`（正文本只挂 `state["results"]`）
- 后果：`score` / `issues` 凭空生成，恒接近满分。**「审计」是空转。**
- spec 依据：f49 §5.2 L696「输入 = outline_id + 章内容」；f34 §5.1 L283-289「LLM 输入 = chapter.content + 角色/世界观全量」

### P0-2 · 写作链零 F6 上下文注入
`ContextService.render_system_prompt` 生产调用点**仅 chat 轨 1 处**（`deps_chat_agent.py:209`）。三条 book 轨用**逐字复制的硬编码字符串**：
```python
character_summary = "主角自定" if not plan.character_ids else "见角色档案（plan.character_ids）"
```
- 三份副本：`book_service.py:866`、`book_pipeline.py:537`、`book_agentic_pipeline.py:814`
- 后果：角色/世界观/伏笔/前文摘要**全部缺席**写作 prompt
- spec 依据：f6 §1 L20/§2 L31/§11 L457；f3 §10 L489/§11 L506-507/§12 L525

### P0-3 · F3 轨上下文注入恒空
`api/deps.py:194-199` `get_writing_service` **不传 `context_provider`** → 恒落 `NullContextProvider`（`writing_service.py:58`）。
- spec：f3 §11 L506-507「F6 就绪后替换为真实实现，零改动」→ **从未替换**
- 连带：`ContextProviderProtocol`（`domain/ports/context_provider.py:20` 声明 `get_context`）**无实现者**（`ContextService` 只有 `build_context`，名字不同）

### P0-4 · 审计绕过 F34 漂移检测
book 轨审计直接 `llm_client.chat`（`books.py:386` 注入 `LangChainLLMClient().chat`），不走 `chapter_audit_service.audit()`（含 `world_repo` + `select_entities` + `_run_drift_check`，`chapter_audit_service.py:145-244`）。
- F34 在写作链上**仅**经 writer agent 自愿调 `audit_chapter` 工具可达（LLM 可不调）
- spec 依据：f26 L76/L198（`audit_chapter` 须包装 F34）；f34 §1 L21/§5.1 L283-289

---

## P1 缺陷（6 条）

### P1-1 · `chapter.writing_requirements` 零消费（父侧独立发现）
`#1017` 加了字段 + DB 迁移 + GUI 输入框，但**业务层零消费**：
- 模型 `chapter.py:415`、迁移 `migrations_chapter.py:15`、repo `chapter_repo.py:51/161/233` 齐全
- 消费面仅 `context_service.py:70`（校验入参非空）；`infrastructure/agent/` 命中数 **0**
- 后果：GUI「写作要求」框是空气

### P1-2 · `writing_style` book 轨不读
`writing_service.py:66/95/342/384` 正确读取 `request.style_hint or project.config.writing_style`，但 book 轨 brief 写的是**常量祈使句**「遵循项目写作风格与用户偏好」。
- 后果：同一配置，F3/GUI 单章生效、book run 失效
- spec 依据：f44 §5.1 L365

### P1-3 · 世界观双重锁死
1. writer 白名单不含 world 工具（`agentic_writer.py:35-43`，5 只读）
2. **且** `ReaderToolDeps` 未传 `world_service`（`agentic_writer.py:175-180`）→ `reader_tools.py:421` 过滤条件为假 → 工具**根本不物化**
- 对照：chat 轨 4 处均传（`deps_chat_agent.py:228/245/252/292`）
- 后果：世界观设定**在任何路径都到不了 writer** → 设定漂移结构必然
- spec 依据：f10 §11 L849；f6 §3.2 L70-71

### P1-4 · F58/F39 授权未接 writer 轨
两 factory 均不传 `tool_ids`/`skill_ids`（`books.py:356-367`、`deps_agentic_writer.py:86-95`）→ 走 `_WRITER_READER_NAMES` 硬编码兜底。
- 连带：`skill_ids` 恒 None → `_append_skills` 永不执行（`agentic_writer.py:200-204`）→ **F39 skill 注入在所有写作轨失效**
- 生产调用点仅 `deps_chat_agent.py:173-177`
- spec 依据：f58；f39 #522

### P1-5 · 伏笔注入缺失
F42 管线 `_assemble_setting_context` 只注入角色/世界观/大纲，**无伏笔**；`AgentService` 装配无 `foreshadowing_repo`。
- 证据：`agent_service.py:780-807`、`:444-449`、`routers/agent.py:57-65`
- spec 依据：f13 §1 L25 / §5 L642（**验收标准 2「写作时注入伏笔提示」**）

### P1-6 · 全书无每章字数约束
三条 book brief 均无字数；`BookLimits`（`writing_plan.py:86-99`）仅 `max_chapters/max_agent_calls/max_tokens/max_sessions`。
- 对照：F27 有 `min_words`（`agentic_writer_service.py:261`）、chat 轨有 `count_words`
- `project.config.default_words`（`project.py:148`）未被 book 链读取
- 用户视角影响：9 卷 300 万字目标下字数账失控

---

## P2 / 元级问题

### P2-1 · supervisor 决策输入缺书任务上下文
`_build_decision_messages`（`book_agentic_pipeline.py:242-281`）只有各章 name+状态、计数、路由历史、护栏数值；无 one_liner / 大纲切片 / 角色摘要 / 风格偏好。
- spec：f49 §5.3 L707-711

### P2-2 · `--show-context` 恒占位
`cli/commands/write.py:26,155,240-241`：`_SHOW_CONTEXT_NOTE = "(--show-context 功能将在 F6 联调时启用)"` — 功能完全未接。
- spec：f6 §6 L310 / §13 M6 L489

### P2-3 · F6 override 勾选只影响预览
GUI ContextPanel 勾选只作用于 `assemble` 预览（`gui-panel.md` §3.3）；写作请求不接受 `override` 参数。
- spec：f6 §3.3 L111-120

### P2-4 · book-agentic 轨兜底丢 `volume_id`
`book_agentic_pipeline.py:794-800` 兜底 `draft_service.create` 只传 `source_outline_id`，漏 `volume_id`（另两轨都传）。
- 影响：仅服务层兜底路径（经 `save_draft` 工具有卷）

### P2-5 · `#1095` 正文归一未覆盖草稿层
`normalize_chapter_content` 调用点仅 `chapter_service.py:187-188`（建章）、`:260-262`（改章）、`output_service.py:89-90`（导出）；**`draft_service.py` 零调用**。
- 后果：写作 agent 产出正文在草稿层（GUI 预览）未归一

### P2-6 · `build_writer_agent_system_prompt` 4 个死参数
`agentic_writer.py:64-89` 声明 `outline`/`context`/`min_words`/`style_hint`，body 只 render `project_id`/`chapter_id`；模板 `variables: [project_id, chapter_id]`。
- **缓和因素**：同 4 值经 `_build_initial_message` 进了 user 消息（`agentic_writer_service.py:256-264`）→ 属死参数/意图漂移，非契约违背

---

## 🔴 元级：spec 谎报（比其他缺陷更值得注意）

| 位置 | spec 声称 | 实际 |
|---|---|---|
| `specs/f44-book-orchestrator/spec.md:692` | `\| F6 context \| 上下文注入链（章 brief 变量） \| ✅ 已实现 \|` | **零实现**（三份 brief 无 F6 调用） |
| `specs/f6-context/spec.md` §11 L457 | 「F3 写作前调 `build_context`」 | `NullContextProvider` 产线运行中 |

**这是缺陷存活至今的根本原因**：后来者读 spec 以为做完了。

### 四重防线同时失效
1. **spec 说已实现** → 无人质疑
2. **测试恒真同源断言**：`test_book_service.py:646-647` 断的是实现里的字面量（`assert "偏好" in prompt or "风格" in prompt` 匹配硬编码「【风格/偏好注入】」）→ 改成空串仍 PASS
3. **覆盖率门禁测执行不测语义**：`check_coverage.py` 只读 `line-rate`/`branch-rate`；「本应存在却不存在的逻辑」无法度量
4. **contract-guard 不覆盖写作链**：`docs/contract-guard.md:4-5` 契约源仅 `tools/registry.py`

---

## 用户旅程脚本需补的断言（改完代码可直接用）

| 阶段 | 断言 | 对应缺陷 |
|---|---|---|
| stage4 | writer 工具列表含 `get_world_setting` | P1-3 |
| stage6 | 写作 prompt 含**真实角色名**（非「主角自定」） | P0-2 |
| stage6 | 写作 prompt 含**世界观条目** | P0-2 / P1-3 |
| stage6 | 写作 prompt 含**伏笔**（若存在未回收） | P1-5 |
| stage6 | 每章字数符合 `default_words` 预期 | P1-6 |
| stage6 | 审计输入含**该章正文**（从 `/agent/drafts` 取原文比对） | P0-1 |
| stage6 | 审计结论走 F34（含 `character_drift`/`setting_drift` 字段） | P0-4 |
| stage6b | 审计非「恒满分 + 空 issues」（注入问题后应检出） | P0-1 |
| 新增 | `writing_requirements` 写入后进 prompt | P1-1 |
| 新增 | `writing_style` 进 book 轨 prompt | P1-2 |
| 新增 | skill_ids 注入生效（F39） | P1-4 |

**注意**：以上断言在当前代码上**应全部失败**（RED 形态），修复后转绿。
