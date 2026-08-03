<!--
  InkFlow PR 模板（规则，非仅布局）。
  填写时遵守以下规则：
  - 标题遵循 Conventional Commits（feat:/fix:/docs:/refactor:/chore:...），描述小写开头
  - 每个 PR 只解决一个具体问题（scope 隔离）
  - 必须有真实验证证据（测试命令 + 输出），不接受"应该能跑"
-->

## 变更摘要

<!-- 2-3 句话说明：解决什么问题、怎么解决。不要贴大段 diff。 -->

## 关联

- Closes #N
- 关联 ADR：adr/ADR-NNN.md（如适用）
- 关联 spec：specs/fX-xxx/spec.md（feature 必须）

## 验证（必填）

- [ ] 本地命令 + 输出（如 `uv run pytest tests/unit/ -q` → 通过数）
- [ ] ruff / mypy 通过
- [ ] UI 变更附截图（如适用）

## Pre-Submission Checklist

**合并前必须全部完成：**

- [ ] 测试是**有意义**的（损坏代码时能 FAIL，非凑覆盖率）
- [ ] 新增 CLI 测试文件已加入 ci.yml `integration-cli-backend` job（如适用）
- [ ] 项目设定文件同步检查（#23 教训）：
  - [ ] AGENTS.md（里程碑表 / 模块类型谱系 / 时间线概览）
  - [ ] FEATURES.md（功能清单 + 版本映射）
  - [ ] adr/README.md（ADR 索引）或 ADR 内容
  - [ ] ci.yml（新 job / 新测试文件）
  - [ ] spec 头部状态（待实现 🔲 → ✅ 已实现，PR #N）
- [ ] 无 monster files（>900 行）；抑制带理由（`# noqa: X  # reason`）
- [ ] PR 范围单一，只解决本 issue 问题
