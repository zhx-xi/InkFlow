# InkFlow 开发工作流

## 🗂️ 目录结构

```
D:\develop\projects\
├── InkFlow\                         # 主仓库 — main 分支（只读，永远绿色）
│   ├── backend\                     # Python 后端源码
│   ├── .specify\                    # SDD 配置 + 项目章程
│   ├── specs\                       # SDD 规格文件
│   ├── .github\                     # CI 配置
│   └── docs\                        # 架构/产品文档
│       ├── adr\                     # ★ ADR 决策记录（索引 + 编号规则见 adr/README.md）
│       └── ...
│
├── InkFlow-ft\                      # git worktree 工作目录（所有 feature 分支）
│   ├── f1-project-model\            # 当前活跃分支的工作副本
│   └── ...                          # 可并行多个 feature worktree
│
└── InkFlow (hermes workspace)\      # Hermes 工作区（docs 副本 + 管道脚本）
    └── docs\                        # 只存文档副本，不存源码
```

## 🔄 完整工作流

### 1. 创建 Issue（仅一次，功能级）

```bash
# 在 GitHub 上手动创建，或使用 API 批量创建
# 每个功能模块一个 Issue（F1~F7）
# Labels: P0 (Phase 1 核心), P1 (Phase 2), P2 (停车场)
```

### 2. 开始新功能

```bash
# 从 main 创建 feat 分支 + worktree
git branch feat/fX-xxx main
git worktree add ../InkFlow-ft/fX-xxx feat/fX-xxx
git push origin feat/fX-xxx

# 切换到 worktree 目录工作
cd D:\develop\projects\InkFlow-ft\fX-xxx
```

### 3. TDD 实现（SDD 工作流）

```
RED:   写测试 → 运行 → 失败
GREEN: 写最少代码 → 运行 → 通过
REFACTOR: 重构 → 运行 → 仍通过
         → git commit -m "type: message"
```

### 4. 提交规范

```
feat:    新功能         例: feat: implement Project CRUD
fix:     Bug 修复       例: fix: project name validation too strict
test:    测试添加/修改   例: test: add ProjectRepository tests
refactor: 重构           例: refactor: extract ProjectValidator
docs:    文档            例: docs: update API contract
chore:   构建/CI/工具    例: chore: configure ruff import sort
```

### 5. 创建 PR + CI 验证

```bash
# 在 feature worktree 内操作
cd D:\develop\projects\InkFlow-ft\fX-xxx

# 确保最新
git pull origin main --rebase

# 创建 PR（分支名自动关联 Issue）
gh pr create \
  --title "F1: 项目/书籍管理" \
  --body "Closes #1" \
  --label "P0" \
  --base main

# CI 自动运行：Ruff → Mypy → pytest → coverage

# PR 通过 CI 后，自行 approve + merge
gh pr merge --squash --delete-branch
```

### 6. 清理 worktree

```bash
# 回到主仓库
cd D:\develop\projects\InkFlow

# 删除本地分支 + worktree
git branch -d feat/fX-xxx
git worktree remove ../InkFlow-ft/fX-xxx

# 删除 worktree 目录
Remove-Item -Recurse -Force ../InkFlow-ft/fX-xxx

# 锁定分支不再需要（远程已删除）
```

### 7. 开始下一个功能

回到 **步骤 2**。

## 📐 ADR 决策记录

所有架构决策记录在 `docs/adr/ADR-NNN.md`，索引见 `docs/adr/README.md`。

**编号规则**：
- 顺序递增，不复用编号（ADR-001, 002, ...）
- 决策被取代时：旧 ADR 标记 `已弃用` 并指向新 ADR；新 ADR 标记 `已接受` 并注明替代关系（如 ADR-005 → ADR-005v2）

**新增/修改流程**：
1. 创建 `docs/adr/ADR-NNN.md`（Nygard 格式：状态 / 背景 / 决策 / 备选方案 / 影响）
2. 更新 `docs/adr/README.md` 索引表
3. 与代码变更同 PR 提交（决策先行：先改 ADR，再改代码）

**使用纪律**：
- 动手改代码前先查相关 ADR；PR 描述引用 ADR 编号
- Constitution §7.3：所有 ADR 保持最新
- 架构分析文档只保留 ADR 索引表，不维护内嵌副本

## ⚡ 单人开发简化规则

| 环节 | 简化方式 |
|------|---------|
| Issue | 功能级粒度（F1~F7），不做 TDD 级子 Issue |
| 分支 | `feat/fX-xxx` 命名，`git worktree` 隔离 |
| PR | 自己创建、自己 approve、自己 merge |
| CI | 只有 PR 触发，main 不允许直接 push |
| 提交 | Conventional Commits，但不要求 squash |
| 清理 | feature 完成后立即清理 worktree + 本地分支 |
