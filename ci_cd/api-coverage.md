# InkFlow API 端点覆盖清单

> 生成日期：2026-08-06（Issue #104「API 端点 100% 有测试」Phase 2 登记件）
> 统计来源：`backend/src/inkflow/api/routers/*.py`（14 个 router）逐文件枚举 + `backend/src/inkflow/api/app.py` 的 `/health`

## 总览

| 指标 | 数值 |
|---|---|
| 端点总数 | **97**（96 个 `@router.*` 装饰器 + 1 个 `@app.get("/health")`） |
| 已覆盖 | **97** |
| 缺口 | **0** |
| 端点覆盖率 | **100%** |

非业务端点（不计入总数）：`/docs`、`/redoc`、`/openapi.json`（FastAPI 自动生成，`tests/api/test_token_auth.py` 有访问性覆盖）；TokenAuthMiddleware 为 ASGI 中间件非端点（`tests/api/test_token_auth.py` 覆盖 401/白名单/JWT 模式）。

## 按模块端点 × 测试覆盖

### project（6 端点）— `tests/api/test_project_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/projects` | ✅ | tests/api/test_project_api.py |
| GET | `/api/v1/projects` | ✅ | tests/api/test_project_api.py |
| GET | `/api/v1/projects/{project_id}` | ✅ | tests/api/test_project_api.py |
| PATCH | `/api/v1/projects/{project_id}` | ✅ | tests/api/test_project_api.py |
| DELETE | `/api/v1/projects/{project_id}` | ✅ | tests/api/test_project_api.py |
| POST | `/api/v1/projects/{project_id}/restore` | ✅ | tests/api/test_project_api.py |

### chapter（11 端点）— `tests/api/test_chapter_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/volumes` | ✅ | tests/api/test_chapter_api.py |
| GET | `/api/v1/projects/{project_id}/volumes` | ✅ | tests/api/test_chapter_api.py |
| GET | `/api/v1/volumes/{volume_id}` | ✅ | tests/api/test_chapter_api.py（补测 2026-08-06） |
| PATCH | `/api/v1/volumes/{volume_id}` | ✅ | tests/api/test_chapter_api.py（补测 2026-08-06） |
| DELETE | `/api/v1/volumes/{volume_id}` | ✅ | tests/api/test_chapter_api.py（补测 2026-08-06） |
| POST | `/api/v1/projects/{project_id}/chapters` | ✅ | tests/api/test_chapter_api.py |
| GET | `/api/v1/projects/{project_id}/chapters` | ✅ | tests/api/test_chapter_api.py（补测 2026-08-06） |
| GET | `/api/v1/chapters/{chapter_id}` | ✅ | tests/api/test_chapter_api.py（补测 2026-08-06） |
| PATCH | `/api/v1/chapters/{chapter_id}` | ✅ | tests/api/test_chapter_api.py |
| DELETE | `/api/v1/chapters/{chapter_id}` | ✅ | tests/api/test_chapter_api.py |
| POST | `/api/v1/chapters/{chapter_id}/move` | ✅ | tests/api/test_chapter_api.py |

### writing（4 端点）— `tests/api/test_writing_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/writing/generate` | ✅ | tests/api/test_writing_api.py |
| POST | `/api/v1/writing/continue` | ✅ | tests/api/test_writing_api.py |
| POST | `/api/v1/writing/revise` | ✅ | tests/api/test_writing_api.py |
| POST | `/api/v1/writing/stream` | ✅ | tests/api/test_writing_api.py |

### agent（5 端点）— `tests/api/test_agent_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/agent/pipelines/execute` | ✅ | tests/api/test_agent_api.py |
| GET | `/api/v1/agent/pipelines/executions/{execution_id}` | ✅ | tests/api/test_agent_api.py |
| GET | `/api/v1/agent/pipelines/executions` | ✅ | tests/api/test_agent_api.py |
| POST | `/api/v1/agent/pipelines/validate` | ✅ | tests/api/test_agent_api.py |
| GET | `/api/v1/agent/pipelines/templates` | ✅ | tests/api/test_agent_api.py |

### characters（16 端点）— `backend/tests/unit/api/routers/test_character_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/characters/extract` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| POST | `/api/v1/projects/{project_id}/characters` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| GET | `/api/v1/projects/{project_id}/characters` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| GET | `/api/v1/characters/{character_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| PATCH | `/api/v1/characters/{character_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| DELETE | `/api/v1/characters/{character_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| POST | `/api/v1/characters/{character_id}/restore` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| GET | `/api/v1/characters/{character_id}/relations` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| POST | `/api/v1/characters/{character_id}/relations` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| PATCH | `/api/v1/characters/{character_id}/relations/{relation_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| DELETE | `/api/v1/characters/{character_id}/relations/{relation_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| POST | `/api/v1/projects/{project_id}/character-groups` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| GET | `/api/v1/projects/{project_id}/character-groups` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| GET | `/api/v1/character-groups/{group_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| PATCH | `/api/v1/character-groups/{group_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |
| DELETE | `/api/v1/character-groups/{group_id}` | ✅ | backend/tests/unit/api/routers/test_character_api.py |

### world_settings（8 端点）— `backend/tests/unit/api/routers/test_world_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/world-settings/extract` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| POST | `/api/v1/projects/{project_id}/world-settings` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| GET | `/api/v1/projects/{project_id}/world-settings` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| GET | `/api/v1/projects/{project_id}/world-settings/categories` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| GET | `/api/v1/world-settings/{setting_id}` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| PATCH | `/api/v1/world-settings/{setting_id}` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| DELETE | `/api/v1/world-settings/{setting_id}` | ✅ | backend/tests/unit/api/routers/test_world_api.py |
| POST | `/api/v1/world-settings/{setting_id}/restore` | ✅ | backend/tests/unit/api/routers/test_world_api.py |

### outlines（19 端点）— `backend/tests/unit/api/routers/test_outline_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/outlines/generate` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/projects/{project_id}/outlines` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/projects/{project_id}/outlines` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/outlines/{outline_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| PATCH | `/api/v1/outlines/{outline_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| DELETE | `/api/v1/outlines/{outline_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/outlines/{outline_id}/restore` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/outlines/{outline_id}/plot-points` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/outlines/{outline_id}/plot-points` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/plot-points/{point_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| PATCH | `/api/v1/plot-points/{point_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| DELETE | `/api/v1/plot-points/{point_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/plot-points/{point_id}/restore` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/projects/{project_id}/story-arcs` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/projects/{project_id}/story-arcs` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| GET | `/api/v1/story-arcs/{arc_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| PATCH | `/api/v1/story-arcs/{arc_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| DELETE | `/api/v1/story-arcs/{arc_id}` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |
| POST | `/api/v1/story-arcs/{arc_id}/restore` | ✅ | backend/tests/unit/api/routers/test_outline_api.py |

### timeline（8 端点）— `backend/tests/unit/api/routers/test_timeline_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/timeline/events` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| GET | `/api/v1/projects/{project_id}/timeline/events` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| GET | `/api/v1/projects/{project_id}/timeline` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| GET | `/api/v1/projects/{project_id}/timeline/check` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| GET | `/api/v1/timeline/events/{event_id}` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| PATCH | `/api/v1/timeline/events/{event_id}` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| DELETE | `/api/v1/timeline/events/{event_id}` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |
| POST | `/api/v1/timeline/events/{event_id}/restore` | ✅ | backend/tests/unit/api/routers/test_timeline_api.py |

### foreshadowings（8 端点）— `backend/tests/unit/api/routers/test_foreshadowing_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/foreshadowings` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| GET | `/api/v1/projects/{project_id}/foreshadowings` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| GET | `/api/v1/foreshadowings/{foreshadowing_id}` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| PATCH | `/api/v1/foreshadowings/{foreshadowing_id}` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| DELETE | `/api/v1/foreshadowings/{foreshadowing_id}` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/restore` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/resolve` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/reopen` | ✅ | backend/tests/unit/api/routers/test_foreshadowing_api.py |

### extractions（4 端点）— `backend/tests/unit/api/routers/test_extractions_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/extract` | ✅ | backend/tests/unit/api/routers/test_extractions_api.py |
| GET | `/api/v1/projects/{project_id}/extractions/runs` | ✅ | backend/tests/unit/api/routers/test_extractions_api.py |
| POST | `/api/v1/projects/{project_id}/vector/reindex` | ✅ | backend/tests/unit/api/routers/test_extractions_api.py |
| POST | `/api/v1/projects/{project_id}/vector/retrieve` | ✅ | backend/tests/unit/api/routers/test_extractions_api.py |

### audit（1 端点）— `backend/tests/unit/api/routers/test_audit_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| GET | `/api/v1/projects/{project_id}/audit` | ✅ | backend/tests/unit/api/routers/test_audit_api.py |

### style（1 端点）— `backend/tests/unit/api/routers/test_style_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/style/analyze` | ✅ | backend/tests/unit/api/routers/test_style_api.py |

### context（3 端点）— `backend/tests/unit/api/routers/test_context_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/context/assemble` | ✅ | backend/tests/unit/api/routers/test_context_api.py |
| GET | `/api/v1/context/chapters/{chapter_id}/summary` | ✅ | backend/tests/unit/api/routers/test_context_api.py |
| POST | `/api/v1/context/chapters/{chapter_id}/summary/refresh` | ✅ | backend/tests/unit/api/routers/test_context_api.py |

### settings（2 端点）— `tests/api/test_settings_api.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| POST | `/api/v1/settings/llm-keys` | ✅ | tests/api/test_settings_api.py |
| POST | `/api/v1/settings/llm/test` | ✅ | tests/api/test_settings_api.py |

### 系统（1 端点）— `tests/api/test_health.py`

| 方法 | 端点 | 覆盖 | 测试文件 |
|---|---|---|---|
| GET | `/health` | ✅ | tests/api/test_health.py |

## 附录：RAG 覆盖口径更新登记（#273）

- **历史冲突**：`src/inkflow/rag/langchain_vector_store.py` 曾依赖 chromadb C 扩展，与 coverage 追踪器同进程运行时崩溃（F14 先例，2026-08 排查结论），`tests/unit/test_langchain_vector_store.py` 被 `pytest --ignore` 排除，覆盖率以「测试方法全覆盖」为替代证据。
- **#273 实证修复**：冲突已于 #273 实证修复（#276 hnsw:sync_threshold=3 + chromadb 1.5.9），`tests/unit/test_langchain_vector_store.py` 已进 cov 口径（不再 `--ignore`），`langchain_vector_store.py` 真实覆盖 99%（171 行 0 miss，2 partial branch）。
- **门禁达成**：完整 CI 口径 line=98.77% / branch=96.06%，coverage-backend 门禁（line ≥ 98.5%、branch ≥ 95%）达成。
- **omit 说明**：`omit = ["*/test_*.py", "*/tests/*"]` 仍排除测试代码自身参与覆盖统计。
