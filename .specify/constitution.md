# InkFlow 项目章程（Constitution）

> 本文件为 InkFlow 项目的"宪法"，定义项目的根本原则、开发规范和决策框架。
> 所有代码、架构和流程决策必须与此章程一致。

## 1. 🎯 使命与定位

**使命**: 打造中国人自己的 AI 辅助小说创作工具，让创作者从重复性工作中解放，专注于故事本身。

**定位**: 本地优先 + 前后端分离 + CLI/Web/MCP 三界面 + 多模型 BYOK 的小说创作工具。

**目标用户**: 独立网文作者、同人写手、剧本创作者、AI Agent 调用方。

## 2. 🏗️ 架构原则

### 2.1 Protocol-First（接口优先）
- 所有跨模块依赖必须通过 Python `Protocol` 抽象
- 业务逻辑只依赖抽象，不依赖具体实现
- 本地/云端通过 DI 容器切换，业务代码零修改

### 2.2 依赖注入
- 所有 Service 的依赖通过构造函数注入
- 禁止全局单例（`config` 模块为唯一例外）
- 测试时轻松 Mock 替换

### 2.3 单一职责
- 一个模块只做一件事
- Service 不直接访问数据库（通过 Repository 层）
- API 路由不包含业务逻辑（委派给 Service）

### 2.4 模块边界清晰
```python
# ✅ 正确: 清晰分层
api/       → 路由层（FastAPI router）
services/  → 业务逻辑层
models/    → 数据模型层（Pydantic + SQLAlchemy）
providers/ → 外部服务适配层
core/      → 基础设施层（配置/日志/DB）
```

## 3. 🧪 质量规范

### 3.1 TDD 强制（Red-Green-Refactor）
- **生产代码必须由失败的测试驱动**
- 每一行新代码都必须有对应的测试
- 先在 `tests/` 写测试，验证失败，再实现，验证通过
- 参见 `test-driven-development` skill

### 3.2 测试覆盖标准
| 阶段 | 覆盖率 | E2E 数 | Flaky |
|------|--------|--------|-------|
| Phase 1 | ≥ 50% | ≤ 20 | 0 |
| Phase 2 | ≥ 60% | ≤ 40 | 0 |
| Phase 3 | ≥ 70% | ≤ 50 | 0 |

### 3.3 CI 必须项
- ✅ PR 自动运行全部测试
- ✅ Ruff lint 检查
- ✅ Mypy 类型检查（Phase 2 起）
- ✅ 覆盖率检查
- ✅ Flaky test = 0（发现即修复）

## 4. 📝 代码规范

### 4.1 命名规范
- `snake_case` — 变量/函数/方法/模块
- `PascalCase` — 类/类型别名
- `UPPER_CASE` — 常量
- 私有成员以 `_` 开头
- 避免单字母变量名

### 4.2 类型注解
- 所有函数必须有类型注解（返回值和参数）
- 复杂类型使用 `type alias` 命名
- `Optional[X]` 优先于 `X | None`（兼容性）

### 4.3 错误处理
- 自定义异常继承 `InkFlowError`
- API 层统一异常处理，不暴露内部细节
- CLI 层捕获所有异常并输出友好的错误信息

## 5. 🔐 安全规范

### 5.1 密钥管理
- API Key 使用 AES-256-GCM 加密存储
- 密钥通过环境变量 `INKFLOW_SECRET_KEY` 注入
- 密钥绝不硬编码或提交到 Git

### 5.2 数据安全
- 本地模式：数据存用户指定的 `data_dir`
- 所有用户数据本地存储，不外传
- 无遥测/分析数据收集

## 6. 🚀 提交规范

### 6.1 Conventional Commits
```
feat:    新功能
fix:     Bug 修复
refactor: 重构
test:    测试添加/修改
docs:    文档
chore:   构建/CI/工具
style:   代码格式
perf:    性能优化
```

### 6.2 提交粒度
- 功能开发：每个完整的 TDD 循环一个提交
- Bug 修复：修复测试 + 代码 + 验证在一个提交
- 禁止：超过 200 行改动的单次提交（重构除外）

## 7. 📐 SDD 工作流

### 7.1 开发流程
```
Constitution → Spec → Clarify → Plan → Tasks → Implement → Converge
```

### 7.2 关键规则
- **Constitution**: 一次性建立，仅通过 PR 修改
- **Spec**: 功能级规格，实现前必须 Review
- **Plan**: 包含技术方案、文件列表、测试策略
- **Tasks**: 每个任务 2-5 分钟，一个 TDD 循环
- **Implement**: 严格按 Tasks 执行，不跳步

## 8. 🔴 红线（禁止行为）
1. ❌ 写生产代码不写测试
2. ❌ 提交失败的测试到主分支
3. ❌ 密钥/Token 提交到 Git
4. ❌ 跨模块循环依赖
5. ❌ 在 API 路由中直接操作数据库
6. ❌ 在 Service 层使用 HTTP 细节（Request/Response）
7. ❌ 全局 mutable 状态（config 只读字段除外）
