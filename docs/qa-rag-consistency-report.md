# InkFlow RAG 三点增强方案 — 数据一致性风险分析与测试策略（QA 评审报告）

> 角色：QA 工程师 / 数据一致性专家
> 评审对象：① embedding 模型一致性（提示 + 重新向量化按钮）② 切片方式可配置（段落/对话/大模型三档 + 滑动重叠 10%-20%）③ 存储元数据补强（项目、章节 x/y；世界观改直查 DB）
> 代码基线：`D:\develop\projects\InkFlow`（已核实 `deps.py get_vector_store` 单例、`_chunking.py chunk_text`、`extraction_service.reindex`、`langchain_vector_store.py`、`search_service.py`、`test_deps_embedding.py` 等）
> 日期：2026-08-12

---

## 0. 现状事实核查（报告的立论基础，均已读码确认）

| 项 | 现状 | 对方案的影响 |
|---|---|---|
| embedding 装配 | `deps._vector_store` 模块级单例，懒加载后**永不刷新**；从 ProviderConfig 注册表取首个 `type="embedding"` 模型构造 `OpenAIEmbeddings` | 改模型配置后，**运行中的进程查询与 reindex 仍用旧模型**——「重新向量化」按钮若不先刷新单例，等于用旧模型重写一遍旧向量，按钮形同虚设 |
| 向量指纹 | **无**。向量库不记录 embedding 模型/维度/切片参数 | 模型切换后新旧向量混库/查询错配**零检测**，静默劣化 |
| 切片 | `chunk_text` 纯函数：~500 字、标点回溯、**无重叠**、块 id=`{chapter_id}:{idx}`；仅章节切片 | 块 id 是**位置索引**——切片参数一改，边界整体漂移，id 命名空间错位；重叠模式上线后「拼接还原原文」不变式被打破（spec 需改） |
| reindex | `extraction_service.reindex`：分页拉取 → `index_batch` **纯 upsert，不删除任何 stale 数据**；无锁 | 章节缩水/删除、切片参数变更后，**旧 chunk 永久残留** → 幽灵检索结果 |
| 存储 | Chroma 单 PersistentClient，每 EntityType 一个 collection，`hnsw:space=cosine` + `sync_threshold=3`（已踩坑修复）；项目隔离=metadata.where | collection **维度在建库时固定**——换不同维度模型必须重建 collection，否则硬失败 |
| 检索 | score=1-distance、min_score 过滤、跨类型合并排序 top_k | 合并无去重；模型切换后分数分布漂移，min_score 语义失效 |
| 检索降级 | semantic 异常 → loguru + 200 空结果（E12）；未配置 embedding → `get_vector_store_optional()` 返回 None | stale 状态下语义搜索仍 200，用户无感知——需要显式 stale 提示而非静默空结果 |
| 设置存储 | `app_settings` 全局键值表（INSERT OR REPLACE）；项目级配置 precedent：`project config extra`（timeline_auto_extract） | 指纹若存 app_settings 是**全局的**，与「按项目 reindex」粒度不匹配；且与 chroma 不同存储，无法原子提交 |
| 既有测试 | `test_langchain_vector_store.py`（FakeEmbeddings 384 维 + 真实 chroma tmp）、`test_deps_embedding.py`（E1-E4 + 单例重置 fixture）、`test_search_semantic.py`、`test_search_service.py`、`tests/api/` 全套 | 指纹/去重/单例刷新测试可**直接复用其 fixture 模式**（详见 §5） |

---

## 1. 风险清单（按严重度排序）

### P0-1 模型切换后向量空间不兼容且无检测 —— 静默劣化（方案①的头号陷阱）

- **触发**：用户把 embedding 模型从 A 换成 B（同 provider 或跨 provider）。
- **机理**：`_vector_store` 单例不刷新 → 查询仍用旧模型 embedding；若单例被刷新（重启后）→ 新模型 query 向量 vs 旧模型存量向量，cosine 相似度**数学上仍可计算但语义上不可比**，检索排序/分数全部失真；`min_score` 阈值语义漂移（模型 B 更保守时结果被误杀，更激进时垃圾结果涌入）。
- **最恶劣形态**：同维度不同模型（如 1536→1536）——**不报任何错**，检索质量悄悄崩坏，用户无法归因；而维度不同（1536→768）时 Chroma collection 维度固定，reindex 直接 500。
- **后果**：用户以为「换了模型 = 检索变好」，实际拿到的是旧模型向量 + 新模型查询的杂交结果；无指纹=无检测=无提示，**比功能缺失更危险**。

### P0-2 「重新向量化」按钮可能写的是旧模型（单例未刷新即 reindex）

- **机理**：按钮 → 调 `POST /vector/reindex` → `ExtractionService._vector_store` 是**旧单例**，其 `_embeddings` 仍是旧模型 → 全量 upsert 用旧 embedding 重写一遍 → 指纹（若按新配置写入）与实际向量不符 → **假成功**。
- **触发**：不重启内核、直接在设置页改模型后点按钮（正是方案①的主流程！）。
- **要求**：reindex 前必须先刷新单例（重建 `LangChainVectorStore` 实例），且「刷新失败必须中止 reindex 并报错」，不允许静默回退旧实例。

### P0-3 维度不匹配 = reindex 硬失败（collection 维度在建库时固定）

- **机理**：Chroma collection 首条写入时确定维度；新模型维度不同时 upsert 抛异常 → reindex 500 → 用户看到「重新向量化失败」，但**没有指引**说明必须重建 collection。
- **要求**：reindex 前探测 collection 现存向量维度（`collection.get(include=["embeddings"], limit=1)`），与目标模型维度比对：不一致 → 走「重建 collection」分支（删除重建 + 全量重灌，见 §3），并明确告知用户这是破坏性操作。

### P1-1 切片方式变更后旧 chunk 残留 —— 幽灵结果（方案②的主陷阱）

- **机理**：reindex 是**纯 upsert**（读码确认无任何 delete）。切片参数从「~500 字标点回溯」改成「按段落」后，同一章节的新块 id（`{chapter_id}:{idx}`）与旧块**边界错位、id 不对齐**：新块数 < 旧块数时，超出的旧 idx 块**永远留在库中**；章节被删除/缩水后同理。
- **后果**：semantic 检索返回**已不存在的文本块**（幽灵内容），SearchService 把块 id 映射回章节 → 用户看到「旧版本章节内容」被检索命中，且 reindex 多少次都清不掉（因为 upsert 只覆盖同名 id）。这是**确定性复现的脏数据**。
- **重叠模式加剧**：10%-20% 滑动重叠下，相邻块共享内容 → 一次检索 top_k 内**同一章节的近似重复块反复命中**（现合并逻辑无去重）→ 结果列表被同一段话刷屏。

### P1-2 reindex 非原子 + 无锁 → 混合状态与假成功

- **机理**：reindex 逐类型 `index_batch`，中途 embedding API 网络失败/进程退出 → 库中**新旧模型向量混合**（若单例已刷新）；无 `asyncio.Lock`（SearchService 的 FTS 有 `_rebuild_lock`，向量 reindex **没有**），API 与 CLI 并发双跑互相踩。
- **假成功**：若指纹在 reindex **开始前**写入 → 失败后状态显示「已向量化」但数据残缺；若在**结束后**写入（commit-last）→ 失败后指纹不更新 → stale 状态保留 → 可重试（upsert 幂等）。**必须 commit-last + 显式 reindexing 状态**。

### P1-3 世界观改直查 DB：双路径结果合并与 SETTING 旧数据

- **机理**：方案③「世界观不需要向量化，直查 DB」→ semantic 检索中 SETTING 类型改为 DB 直查 → 结果评分（DB 无向量分数）与向量结果**不可比**；若只是「不索引新数据」，存量 SETTING 向量仍在 → 检索仍命中 → 行为与方案矛盾；若清理存量，用户升级后世界观语义检索能力**直接消失**（是否预期？需产品拍板）。
- **风险点**：SearchEntityType.WORLD 的 `_SEMANTIC_TYPES` 映射、`_map_retrieved`、E12 降级路径、搜索结果 title/snippet 结构都要同步改，改动面比「加个按钮」大得多，**测试契约必须先 RED**。

### P2-1 元数据 schema 演进（章节 x/y）→ 旧数据缺键

- **机理**：补 project/chapter_x/chapter_y 后，存量 chunk 无新键。现状 `_map_retrieved` 对缺键有 fallback（title 回退 content 前 40 字符、chapter_id 回退块 id 前缀），短期不崩；但**任何新代码直接读 `metadata["chapter_x"]` 就会 KeyError**——必须延续 `.get()` 约定。
- **要求**：schema 版本号入指纹，缺键/旧 schema 一律视为 stale，用「重新向量化」统一收敛，而不是在代码里堆兼容分支。

### P2-2 LLM 分析切片：非确定性 + 成本失控

- **机理**：第三档「大模型分析切片」输出**不可复现**——同一章两次切片边界不同 → chunk id 漂移 → 残留风险放大；且 reindex 全量跑 LLM 切片成本高、慢、可能超时。
- **要求**：必须复用 F14 已有 `_content_hash`（sha256）增量机制——内容未变的章节**跳过 LLM 切片**（直接复用上次切片结果或跳过重灌），否则「重新向量化」对一本 50 万字的书就是一次 LLM 全量重读。

### P3-1 并发/多实例写 Chroma（低概率）

- Chroma PersistentClient 基于 SQLite，双开应用/API+CLI 并发写可能锁冲突。现 app 单实例为主，**降级为 P3**，但 reindex 锁（内存级）挡不住多进程——文档注明即可。

### P3-2 min_score / top_k 语义随模型漂移（与 P0-1 同源，独立成项便于测试断言）

- 换模型后同查询分数整体抬升/压低，用户侧 min_score 配置失真。检测机制无法根治，**靠指纹提示 + 文档说明**，不在本次方案内修。

---

## 2. 检测机制建议（指纹/版本）

### 2.1 指纹内容（一个 JSON blob，三部分）

```json
{
  "schema_version": 2,
  "embedding": {
    "provider": "openai",
    "model_id": "text-embedding-3-small",
    "base_url": "https://api.test.example/v1",
    "dimension": 1536
  },
  "chunking": {
    "mode": "paragraph",            // fixed | paragraph | dialogue | llm
    "chunk_size": 500,              // fixed 模式生效
    "overlap_ratio": 0.15,          // 0 表示无重叠
    "chunker_version": 1            // 切片算法自身版本（改算法必须 +1）
  },
  "indexed_at": "2026-08-12T08:00:00Z",
  "status": "fresh"                 // fresh | stale | reindexing
}
```

- **幂等性**：同配置重复生成必须得到**完全相同**的指纹（字段排序固定、base_url 归一化去尾斜杠）；`embedding` 部分**必须含 base_url**——同模型不同服务商的向量空间不同。
- **变更判定**：有效配置算出的指纹 ≠ 已索引指纹 → stale。**任一字段变更都触发**（含 chunker_version 手动 bump）。

### 2.2 存储位置：专用 `inkflow_meta` collection（推荐，理由充分）

| 候选 | 结论 | 理由 |
|---|---|---|
| **Chroma 专用 `inkflow_meta` collection**（每项目一个 doc，id=`fp:{project_id}`） | ✅ **首选** | 与它描述的向量数据**同库同生命周期**：DB 重建/迁移不会让指纹与向量脱节；支持 per-project（where 过滤）；写入路径与 reindex 同一条（可 commit-last）；读取零额外依赖 |
| `app_settings` 表（F32 已有） | ⚠️ 备选（仅存全局默认值） | 全局粒度与「按项目 reindex」不匹配；跨存储无法与 chroma 原子提交；用户删 chroma 目录后残留误导 |
| project config extra（timeline_auto_extract 先例） | ❌ | 项目配置表随项目删除而删，但 chroma 数据可能还在（重建项目场景），语义错位 |
| collection metadata | ❌ | 每 EntityType 一个 collection，指纹粒度是「类型级」而非「项目级」，且 Chroma 1.x 改 collection metadata 有已知坑（`hnsw:space` 不允许改） |

- **读取时机**：`get_vector_store()` 懒加载时读一次缓存进单例（`_fp_state`），**不要在每次检索时读**（避免查询路径加 I/O）。
- **兼容**：`inkflow_meta` 不存在或其中无 `fp:{project_id}` doc → 状态 = **unknown（视同 stale）**——存量用户升级后第一次打开 RAG 设置页即看到「需要重新向量化」提示，这正是方案①要的行为。

### 2.3 检测时机与失效语义

| 时机 | 动作 | 说明 |
|---|---|---|
| 设置页/RAG 开启流程（GUI） | 调 `GET /vector/status?project_id=` → 返回 `{configured_fp, indexed_fp, stale, reason, dimension_mismatch, counts}` | **方案①的主入口**：stale 时展示「重新向量化」按钮 + 原因文案（「模型已变更」「切片参数已变更」「数据版本过旧」「维度不兼容」） |
| `get_vector_store()` 懒加载 | 计算当前配置指纹 → 与已索引指纹比对 → 缓存 `_fp_state` | 检索不阻塞、不加延迟；仅当 reindex 成功后刷新缓存 |
| CLI `vector retrieve/reindex` | 输出首行 stale 警告（`WARNING: 向量库与当前配置不一致（...），请执行 vector reindex`） | 复用手工冒烟路径，开发者自己先踩到 |
| semantic 检索 | 不阻断、不加 I/O；仅 `logger.warning` 一次（单例缓存，避免刷屏） | stale 状态下**继续用旧向量服务**（200 非空），比 E12 的静默空结果强——用户至少能看到结果 + GUI 横幅 |
| reindex 执行中 | meta doc `status="reindexing"`（先写）→ 完成后 `status="fresh"`（后写） | 失败/崩溃后 status 停在 reindexing → 下次检测视为 stale（**reindexing 超时阈值**：如 24h，防永久卡死） |

### 2.4 维度探测（P0-3 的检测半壁）

- reindex 前：对每个目标 collection `get(include=["embeddings"], limit=1)` 读现存向量维度。
- `现存维度 == 0`（空 collection）→ 直接灌新模型，无冲突。
- `现存维度 == 新模型维度` → 原地 upsert（换模型但同维，仍需全量重灌——旧向量必须被覆盖）。
- `现存维度 != 新模型维度` → **必须重建 collection**（delete + recreate + 全量重灌），接口返回 `collections_recreated: true`，GUI 提示「已重建向量库，需完整重新向量化」。

---

## 3. 迁移与回滚策略

### 3.1 重新向量化协议（三步 + commit-last，顺序不可调换）

```
① 刷新单例：build_vector_store(新配置) → 校验通过后原子替换 deps._vector_store
   （失败 → 保留旧单例，reindex 拒绝执行并报错，杜绝「旧模型重写」）
② upsert 全部新向量（幂等）：按类型分页拉取 → 新切片器 → index_batch
   （LLM 档：内容 sha256 未变的章节跳过，复用 F14 extraction_runs 增量）
③ 清理 stale + 提交指纹：
   3a. 计算源侧 id 全集（DB 投影，与 ② 同一份数据）
   3b. collection.get(where project_id) → 与源侧差集 = 待删 id → delete
       （章节删除/缩水的旧 chunk 在此被清掉 —— 解决 P1-1）
   3c. 写 meta doc：status="fresh" + 新指纹（唯一提交点）
```

- **原子性语义**：任何一步失败 → 指纹未提交 → 状态停留在 stale/reindexing → 用户可安全重试（upsert 幂等 + 差集删除幂等）。**永不出现「指纹说 fresh 但数据是旧的」**。
- **顺序论证**：必须先 upsert 后 delete（而非先清后灌）——先清后灌在失败时会留下**空索引**（比混合索引更糟）；upsert 先行的窗口期内旧数据仍可服务查询。

### 3.2 维度不匹配分支（P0-3 的迁移路径）

```
detect 维度不匹配
 → 备份：shutil.copytree(chroma_dir, chroma_dir + ".bak-<timestamp>")（本地应用，成本可接受）
 → delete collection（inkflow_character 等）→ recreate（新维度）
 → 全量重灌 → 写指纹
 → 成功后删除备份；失败 → 提示用户手动恢复备份目录 + 重启
```

- **明确破坏性**：GUI 必须二次确认（「此操作将清空当前向量库并重建，耗时取决于项目规模」）。
- 同维路径无需备份（upsert 可逆）。

### 3.3 回滚策略

- **回滚 = 再次 reindex**：reindex 是唯一的库变更操作且幂等——用户把模型改回旧配置 → 指纹再次 mismatch → 再点一次重新向量化即可。**不需要**为回滚保留旧向量快照（同维场景）。
- **维度变更场景**：回滚依赖 .bak 备份目录（3.2）或接受一次全量重建；文档写明「维度变更不可原地回滚」。
- **版本兼容**：`schema_version` 前向检查——新代码读到更高版本指纹 → 按 unknown/stale 处理并提示升级，禁止降级解析崩溃。

### 3.4 旧数据清理范围

- 章节删除/缩水 → 差集删除自动清理（3.1 步骤 3b）。
- 世界观退出向量化（方案③）→ 该类型集合按项目 `delete(where project_id)` 清空，**保留空 collection**（避免重建 churn）；指纹的 chunking/scope 字段记录 `setting_indexed: false`。
- 孤儿向量（历史 bug 残留、无源实体）→ 差集删除天然覆盖（源侧全集 = DB 投影）。

---

## 4. 测试覆盖建议（单元 / API / E2E）

> 遵循 SDD+TDD：以下每项先写 RED 契约测试再实现。所有真实 Chroma 测试沿用 F14 坑位：**RAG 测试与 pytest-cov 不能同进程**（chromadb/numpy 冲突），CI 分两次跑。

### 4.1 单元测试（tests/unit/）

**A. 切片器变体（新文件 `test_chunking_modes.py`，镜像 `_chunking.py` 纯函数风格）**
1. paragraph 模式：按空行/段落边界切分；段落超长时降级标点回溯；空文本 → `[]`；`chunk_size<=0` → ValueError（保持既有契约）。
2. dialogue 模式：按说话人切换切分；连续对话块合并；对话 + 叙述混合文本边界正确；**无对话文本 → 行为与 fixed 一致**（降级路径）。
3. LLM 模式：注入 mock analyzer（返回边界列表）→ 断言边界生效；analyzer 异常 → 降级 fixed（**不允许 reindex 整体失败**——P2-2 的失败语义）；**内容 hash 相同 → 不重复调用 analyzer**（增量契约）。
4. 重叠 10%/20%：断言相邻块重叠长度/ratio ∈ 区间；重叠 + 超短文本（< chunk_size）不产生重复块；**不变式变更声明**：overlap>0 时「拼接还原原文」不再成立——补断言 overlap=0 时仍成立，overlap>0 时断言「原文每字符至少被一个块覆盖」（弱不变式）。
5. 块 id 稳定性：`{chapter_id}:{idx}` 格式；切片参数变更 → 断言**同章节 idx 对齐或整体漂移**的预期（为 stale 清理测试提供输入）。

**B. 指纹逻辑（新文件 `test_vector_fingerprint.py`，纯函数，零框架）**
6. 确定性：同配置两次生成指纹完全一致（字段序、base_url 归一化）。
7. 敏感性：model_id / base_url / dimension / chunking 任一字段变更 → 指纹不同；chunker_version bump → 指纹不同。
8. 序列化 roundtrip：dict → JSON → dict 无损。
9. 状态机：`fresh/stale/unknown/reindexing` 四态转换表（unknown 视同 stale；reindexing 超时 → stale）。

**C. 向量库层（扩展现有 `test_langchain_vector_store.py`，复用 FakeEmbeddings + tmp_path fixture）**
10. 维度探测：现存向量 384 维 vs 新 embeddings 768 维 → 返回 `dimension_mismatch=True`（不抛错，由上层决策）；同维 → False。
11. 差集清理：库中 id 集 {a,b,c} vs 源侧 {a,b} → delete 仅删 c；**无源侧数据时清空该项目全部 id**；跨项目隔离（p2 的 c 不删）。
12. meta collection：reindex 流程中「写指纹失败」模拟（注入异常于 3c 之前）→ status 仍为 reindexing/stale，**不得为 fresh**（commit-last 契约）；成功路径 → fresh + 指纹可读回。
13. 去重：重叠切片下同内容相邻块 + 同章节多块命中 → 合并结果按 `(entity_type, 源实体 id)` 去重后再截断 top_k（断言 5 个重复块 → 结果只留 1 个 + 分数取最高）。

**D. 装配层（扩展 `test_deps_embedding.py`，复用 `_reset_vector_store_singleton` fixture）**
14. **E5 单例刷新契约**（新）：配置变更后调用 `refresh_vector_store()` → 返回**新实例**且 `deps._vector_store` 已替换；刷新失败（构造异常）→ 单例保持旧实例 + 异常上抛，**不允许半替换**。
15. E6 维度探测接线：mock collection 维度与目标不一致 → `get_vector_store` 暴露 mismatch 状态（供 status 端点用）。

### 4.2 API 测试（tests/api/，复用 conftest 的 override_get_db）

16. `GET /vector/status`：无 meta doc → `stale=true, reason=unknown`；指纹一致 → fresh；配置变更 → stale + 具体 reason（模型/切片/版本）；**返回 200 而非 404/500**（状态查询不应炸）。
17. `POST /projects/{pid}/vector/reindex` 联动：先改 embedding 配置 → status stale → reindex → status fresh；**reindex 两次幂等**（indexed 数一致、无重复 id、第二次不产生 stale 循环）。
18. 维度不匹配：mock 库中 384 维、新模型 768 维 → reindex 走重建分支 → 返回 `collections_recreated=true` + 旧 id 全部消失 + 新向量可检索。
19. 失败路径：embedding API 抛错（mock）→ reindex 500 + status 仍 stale（**不是** fresh，防假成功）；重试成功 → fresh。
20. 并发：两个并发 reindex（asyncio.gather）→ 内部锁保证串行 → 终态一致、无 500、无重复数据。
21. stale 期间的 semantic 搜索：**200 + 旧向量结果 + 日志警告**（不是 E12 的空结果，也不是 500）——锁定「stale 可服务但可见」语义。
22. 世界观直查：semantic 请求含 WORLD 类型 → 走 DB 直查路径 → 结果结构与向量路径一致（title/snippet/project_id 字段契约不变）；SETTING 存量向量已清 → 不出现混合命中。

### 4.3 E2E 测试（tests/e2e/ Playwright Electron，冒烟级）

23. **设置页 stale 提示流**：改 embedding 模型 → 设置页出现「向量库与当前配置不一致」横幅 + 「重新向量化」按钮 → 点击 → 进度态 → 完成后横幅消失；**重启应用后仍 fresh**（指纹持久化契约——防「每次启动都提示」）。
24. **按钮假成功防护**：改模型后**不重启**直接点重新向量化（P0-2 场景）→ 断言调用链先刷新单例（观察点：reindex 日志中 embedding model id = 新模型）；若实现未刷新单例，此用例必须 RED。
25. **切片模式切换流**：段落 → 对话 → 触发 stale 提示 → 重新向量化 → semantic 搜索返回对话级 chunk（断言结果 snippet 是对话文本）；重叠开关 10% → 搜索结果无相邻重复块（去重生效的 GUI 侧验证）。
26. **世界观直查**：设置开启后，世界观条目不再出现在 semantic 结果、但 keyword 搜索仍命中（双路径行为契约）。
27. **失败恢复**：reindex 中断（kill 内核）→ 重启 → 状态为 stale/reindexing → 再次点击成功 → fresh（崩溃恢复契约）。

---

## 5. 现有测试资产的复用点

| 现有资产 | 复用方式 |
|---|---|
| `tests/unit/test_langchain_vector_store.py` 的 `FakeEmbeddings`（384 维字符袋）+ `store` fixture（真实 Chroma + tmp_path） | 直接用于 §4.1-C 全部用例（维度探测/差集清理/meta collection/去重）；`make_entity` 助手扩展 metadata 参数即可 |
| `tests/unit/test_deps_embedding.py` 的 `_reset_vector_store_singleton` autouse fixture + `_repo_with_providers` + `_embedding_provider` | §4.1-D 单例刷新用例零成本接入；E5/E6 与其 E1-E4 同文件同风格（同 spec 演进，建议并入同一文件） |
| `tests/unit/test_search_semantic.py` | stale 期间检索语义（§4.2-21）、世界观直查路径（§4.2-22）的 mock 底座；其「异常 → 200 空结果」契约需按新语义**修订**（stale ≠ 异常） |
| `tests/unit/test_search_service.py` | `_map_retrieved` 缺键 fallback 断言延续到 chapter_x/chapter_y 新键（P2-1 回归）；去重后 top_k 截断断言 |
| `tests/api/` conftest（override_get_db）+ `test_project_api.py` / extraction API 测试 | §4.2 全部 API 用例的骨架；reindex 端点测试已有先例（幂等断言可复制） |
| CLI 测试（F14 的 `tests/cli` vector 组，CI 显式列表） | CLI stale 警告断言 + 新 `vector status` 子命令；**注意 F14 坑 #8：新增 CLI 测试文件必须显式加入 ci.yml job 列表** |
| F14 `extraction_runs` 表 + `_content_hash`（sha256） | LLM 切片增量跳过的数据源（P2-2）；增量断言在 service 层测试复用其 repo stub |
| `tests/e2e/`（Playwright Electron，inkflow-e2e-testing 契约） | §4.3 用例；设置页既有 E2E 流（0.6.0-S10b 设置 E2E）的 fixture 直接扩展 |
| F14 坑位记录（chromadb 与 pytest-cov 冲突、CI 显式列表、worktree venv） | 新测试文件进 CI 前先对照 F14-HANDOFF §4 清单 |

---

## 6. 结论（给方案的硬性要求清单）

1. **指纹是方案①③的强制性前置**，否则「重新向量化」按钮只是安慰剂——指纹必须含 model_id + base_url + dimension + 切片参数 + schema_version，存 Chroma 专用 `inkflow_meta` collection（per-project），commit-last 提交。
2. **重新向量化 = 刷新单例 → upsert → 差集删除 → 写指纹**，顺序不可调换；任何失败都不得提交指纹（防假成功）；reindex 必须加锁。
3. **reindex 必须补「差集删除」**——这是现有实现的结构性缺陷（纯 upsert），不修的话方案②的切片切换必然制造幽灵 chunk。
4. **维度不匹配走「重建 collection」分支**，GUI 二次确认 + 备份目录；同维换模型原地全量重灌。
5. **世界观直查 DB 的改动面最大**（双路径评分不可比、SETTING 存量清理、检索契约修订），必须先出 spec + RED 契约再动代码。
6. **stale 不是错误**：检索继续服务（旧向量 + 日志警告），GUI 横幅提示——与 E12「异常空结果」明确区分。
7. LLM 切片档必须复用 sha256 增量，否则「重新向量化」成本失控。
8. 测试分层已全部给出可落地清单（§4），复用点明确（§5），建议作为 spec 的 §9 测试契约直接采纳。
