# Contributing to InkFlow

感谢对 InkFlow 的兴趣！这是一个单人主导的开源项目（AI 辅助小说创作工具），采用 **SDD（Spec-Driven Development）+ TDD** 工作流。

## 快速开始

1. **阅读**：`AGENTS.md`（项目总约定 + AI 行为准则）、`ARCHITECTURE.md`（架构导航）、`FEATURES.md`（功能清单）
2. **环境**：Python 3.11+，`backend/` 使用 uv 管理依赖（`uv sync --frozen`）
3. **开发流程**：每个功能先写 spec（`specs/f<X>-<name>/spec.md`）→ 测试先行（RED）→ 实现（GREEN）→ PR

## 分支与 PR 约定

- 分支名：`feat/<slug>`（功能）/ `fix/<slug>`（bug）/ `docs/<slug>`（文档）
- 提交信息：Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` ...），描述小写开头
- PR 标题：同样遵循 Conventional Commits；body 引用 `Closes #<N>`
- 主分支（main）只读：所有变更经 worktree + PR 合入

## 质量标准（PR 必过）

- ruff lint（规则集见 `backend/pyproject.toml`）+ mypy 类型检查（严格化配置）
- 单元 + 集成测试全绿（覆盖率 ≥ 70%）
- 新代码全类型化，无裸 `Any`；抑制必须带理由（`# noqa: X  # reason`）
- 无 monster files（>900 行被 `ci_cd/check_file_length.py` 拦截）
- 详细陷阱清单见 `docs/ai-traps.md`

## 问题报告

Bug / 功能建议走 GitHub Issues；开发中问题（决策/拍板）见 `adr/` 决策记录。
