# Phase 1 Spec — 核心写作引擎

> F1-F7: 项目/章节管理 · AI 写作管道 · Agent 编排 · LLM Provider 适配 · 上下文管理 · CLI 接口

---

## F1: 项目/书籍管理（project_service）

### 概述
用户创建和管理小说项目，每个项目独立配置（AI 模型、Agent 角色、写作风格）。

### 数据模型
```python
class Project(Base):
    __tablename__ = "projects"
    id: int          # 主键，自增
    name: str        # 项目名称
    genre: str       # 题材（玄幻/科幻/言情/...）
    language: str    # 语言（zh-CN/en/...）
    target_words: int # 目标字数
    config: dict     # JSON: AI 模型配置、Agent 角色配置、写作风格
    created_at: datetime
    updated_at: datetime
```

### API 契约
| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/v1/projects | 创建项目 |
| GET | /api/v1/projects | 项目列表 |
| GET | /api/v1/projects/{id} | 项目详情 |
| PATCH | /api/v1/projects/{id} | 更新项目 |
| DELETE | /api/v1/projects/{id} | 删除项目（软删除→回收站）|

### CLI 命令
```bash
inkflow project create --name "xxx" --genre xuanhuan --language zh-CN --target-words 100000
inkflow project list [--search xxx] [--sort name]
inkflow project get --id 1 [--json]
inkflow project delete --id 1 [--force]
```

### 边界情况
- 项目名称不能为空（验证 1-100 字符）
- 删除时如有关联章节需二次确认（CLI: `--force` 跳过确认）
- 项目配置 JSON 使用 Pydantic 模型验证

### 测试策略
- `test_create_project` — 成功创建并返回 ID
- `test_create_project_empty_name` — 空名称返回 422
- `test_list_projects` — 返回分页列表
- `test_delete_project_with_chapters` — 有章节时需确认

---

## F2: 章节管理（chapter_service）

### 概述
卷/章节层级管理，章节内容编辑，状态追踪（draft→writing→review→final）。

### 数据模型
```python
class Volume(Base):
    __tablename__ = "volumes"
    id: int
    project_id: int  # FK → projects.id
    title: str
    order_index: int

class Chapter(Base):
    __tablename__ = "chapters"
    id: int
    project_id: int       # FK
    volume_id: int        # FK → volumes.id（可为 null）
    title: str
    content: str          # Markdown 文本
    status: ChapterStatus # draft / writing / review / final
    word_count: int
    order_index: int
    created_at: datetime
    updated_at: datetime
```

### API 契约
| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /api/v1/chapters | 创建章节 |
| GET | /api/v1/chapters?project_id=N | 章节列表 |
| GET | /api/v1/chapters/{id} | 章节详情（含内容）|
| PATCH | /api/v1/chapters/{id} | 更新章节 |
| DELETE | /api/v1/chapters/{id} | 删除章节 |
| POST | /api/v1/chapters/{id}/move | 移动章节（跨卷）|
| PATCH | /api/v1/chapters/{id}/status | 变更状态 |

### CLI 命令
```bash
inkflow chapter create --project-id 1 --title "第一章" --volume-id 1
inkflow chapter list --project-id 1 [--json]
inkflow chapter get --id 1 [--json]
inkflow chapter update --id 1 --title "新标题"
inkflow chapter delete --id 1 [--force]
```

### 测试策略
- `test_create_chapter_in_volume` — 在卷中创建章节
- `test_chapter_list_pagination` — 分页列表
- `test_chapter_status_transitions` — 状态枚举正确转换
- `test_chapter_word_count_update` — 内容变更自动更新字数

---

## F3: AI 写作管道（writing_service）

### 概述
核心价值功能——AI 辅助生成、续写、修改章节内容。

### 功能流程
```
用户输入 (Prompt/Outline)
  → 格式校验
  → 上下文组装 (context_service)
  → LLM 调用 (llm_service)
  → 输出格式校验
  → [失败则重试 ≤ 3 次]
  → 返回结果
```

### 接口
```python
class WritingService:
    async def generate_chapter(
        project_id: int,
        outline: str,
        context: WritingContext,
    ) -> str: ...

    async def continue_writing(
        chapter_id: int,
        next_prompt: str,
    ) -> str: ...

    async def revise_content(
        chapter_id: int,
        feedback: str,
        scope: str = "paragraph",  # paragraph | section | full
    ) -> str: ...
```

### 格式校验
- 输出必须有正确章节结构（标题、段落）
- 中文字数 ≥ 2000（可配）
- 格式异常 → 自动重试 ≤ 3 次，每次附带前次错误信息

### 测试策略
- `test_generate_chapter_basic` — 基本生成（Mock LLM）
- `test_generate_chapter_format_retry` — 格式异常触发重试
- `test_continue_writing_style_consistency` — 续写风格一致
- `test_revise_content_valid` — 修改指定段落

---

## F4: Agent 编排（agent_service）

### 概述
多角色 Agent 协作完成写作任务（Architect→Writer→Auditor→Reviser）。

### 角色定义
| 角色 | 职责 | 默认 Prompt | 建议模型 |
|------|------|------------|---------|
| Architect | 规划章节结构、情节走向 | 大纲规划 Prompt | GPT-4 / Claude 3.5+ |
| Writer | 执行写作、生成内容 | 写作 Prompt | GPT-4 / DeepSeek |
| Auditor | 审校文稿、发现问题 | 审校 Prompt | Claude / GPT-4 |
| Reviser | 根据审校意见修订 | 修订 Prompt | 任意模型 |

### 编排流程
```
1. Architect → 生成章节大纲
2. Writer → 根据大纲写章节
3. Auditor → 审校章节
4. [若发现问题] Reviser → 修订
5. [可选] 循环 2-4 直到 Auditor 通过
```

### 测试策略
- `test_agent_chain_execution` — 链式执行完整流程
- `test_agent_skip_role` — 跳过指定角色
- `test_agent_retry_on_failure` — 角色失败重试

---

## F5: LLM Provider 适配（llm_service）

### 概述
统一接口对接多家 LLM 供应商。Phase 1 实现 OpenAI + DeepSeek + Ollama。

### 接口定义
```python
class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict], **kwargs
    ) -> ChatResponse: ...
    async def stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]: ...
    async def count_tokens(self, text: str) -> int: ...
```

### 内置 Provider
| Provider | 类名 | 验证状态 |
|----------|------|---------|
| OpenAI | OpenAIProvider | Phase 1 实现 |
| DeepSeek | DeepSeekProvider | Phase 1 实现 |
| Ollama | OllamaProvider | Phase 1 实现 |
| Anthropic | AnthropicProvider | Phase 1 可选 |

### 密钥管理
- AES-256-GCM 加密存储（`cryptography` 库）
- 密钥表 `api_keys { id, provider, key_encrypted, project_id }`

### 测试策略
- `test_openai_chat_mock` — Mock HTTP 测试 OpenAI chat
- `test_deepseek_stream_mock` — Mock 测试 DeepSeek 流式
- `test_key_encryption_decryption` — 密钥加密解密
- `test_provider_registry` — 自动注册发现

---

## F6: 上下文管理（context_service）

### 概述
智能管理 LLM Prompt 的上下文注入，确保 Token 不超限。

### 分层策略
| 层级 | 内容 | 策略 |
|------|------|------|
| protected | 当前章节大纲、写作要求 | 必须包含 |
| compressible | 角色设定、世界设定 | 可摘要压缩 |
| dynamic | 前文摘要、伏笔提醒 | 按 Token 预算自动选择 |

### Token 预算
```
模型窗口 80% = 可用 Token
├── protected (20%)     ← 固定
├── compressible (40%)  ← 可压缩
└── dynamic (20%)       ← 根据剩余空间决定
```

### 测试策略
- `test_token_budget_allocation` — Token 预算分配正确
- `test_context_layers_assembly` — 分层组装
- `test_context_compression` — 超预算时压缩
- `test_character_context_injection` — 角色设定注入匹配

---

## F7: CLI 命令行接口（cli_interface）

### 概述
Typer CLI，所有核心操作可通过命令行完成，支持 `--json` 输出。

### 命令树
```
inkflow
├── serve           # 启动 Web 服务
├── project
│   ├── create      # 创建项目
│   ├── list        # 项目列表
│   ├── get         # 项目详情
│   ├── update      # 更新项目
│   └── delete      # 删除项目
├── chapter
│   ├── create      # 创建章节
│   ├── list        # 章节列表
│   ├── get         # 章节详情
│   ├── update      # 更新章节
│   ├── delete      # 删除章节
│   └── move        # 移动章节
├── write
│   └── next        # 生成下一章节
├── llm
│   ├── list        # 列出 Provider
│   └── set-key     # 设置 API Key
└── config
    ├── show        # 显示配置
    └── set         # 修改配置
```

### `--json` 输出规范
- 所有命令默认人类可读（Rich 彩色）
- `--json` 标志切换到 JSON 输出
- JSON Schema 定义输出格式，便于 Agent 消费

### 测试策略
- `test_cli_help` — 每级命令 --help 正常
- `test_cli_json_output` — --json 输出可解析
- `test_cli_project_create` — E2E 创建项目
- `test_cli_serve_startup` — serve 命令可用

---

## 文件结构

```
src/inkflow/
├── __init__.py
├── __main__.py          # CLI 入口
├── api/
│   ├── __init__.py
│   ├── app.py           # FastAPI 应用
│   ├── projects.py      # F1 路由
│   ├── chapters.py      # F2 路由
│   └── writing.py       # F3 路由
├── models/
│   ├── __init__.py
│   ├── base.py          # SQLAlchemy Base + 引擎
│   ├── project.py       # F1 模型
│   ├── chapter.py       # F2 模型
│   └── enums.py         # 共享枚举
├── services/
│   ├── __init__.py
│   ├── project.py       # F1 服务
│   ├── chapter.py       # F2 服务
│   ├── writing.py       # F3 服务
│   ├── agent.py         # F4 服务
│   ├── llm.py           # F5 服务
│   └── context.py       # F6 服务
├── providers/
│   ├── __init__.py
│   ├── base.py          # LLMClient Protocol
│   ├── openai.py        # F5 OpenAI
│   ├── deepseek.py      # F5 DeepSeek
│   └── ollama.py        # F5 Ollama
├── cli/
│   ├── __init__.py
│   ├── project.py       # F7 project 子命令
│   ├── chapter.py       # F7 chapter 子命令
│   ├── write.py         # F7 write 子命令
│   └── config.py        # F7 config 子命令
└── core/
    ├── __init__.py
    ├── config.py        # 配置
    ├── log.py           # 日志
    └── database.py      # 数据库连接
tests/
├── conftest.py
├── test_health.py
├── test_project.py      # F1
├── test_chapter.py      # F2
├── test_writing.py      # F3
├── test_agent.py        # F4
├── test_llm.py          # F5
├── test_context.py      # F6
└── test_cli.py          # F7
```

---

## Phase 1 Gate 检查清单

- [ ] 可通过 CLI 完成「建书→写章节→审校」完整流程
- [ ] ≥ 3 个 LLM Provider 可用（含 Mock 测试）
- [ ] `inkflow serve` 启动 Web 服务
- [ ] 云端 Protocol 接口全部定义完毕
- [ ] 测试覆盖率 ≥ 50%
- [ ] Bug-to-Feature ≤ 1.0:1
- [ ] CI 绿色通过
