# F30 内核冷启动基建 — 实施计划（Plan）

> **依据**: `specs/f30-kernel-bootstrap/spec.md` v1.1 | Constitution P3 (TDD), P4 (依赖方向)
> **关联**: Issue #166（0.5.0）· ADR-030（② 冷启动协议）· ADR-021（端口文件/token 契约）
> **分支**: `feat/kernel-bootstrap`（worktree `D:\develop\projects\InkFlow-ft\kernel-bootstrap`）

## 依赖方向检查

```
✅ cli/commands/kernel.py → infrastructure/kernel/（ensure_kernel）→ core/config（data_dir）· 标准库（subprocess/ctypes）
✅ infrastructure/kernel/ 零依赖 api/ domain/（纯客户端基建）
❌ infrastructure/kernel/ 不得 import FastAPI / SQLAlchemy
```

## 批次结构

| 批 | 内容 | 文件集 | 执行者 | 验证 |
|----|------|--------|--------|------|
| RED-1 | state + version 契约 | `backend/tests/unit/test_kernel_state.py` + `test_kernel_version.py` | delegate_task（tdd-test-developer） | 主 agent 亲自跑：收集期 ModuleNotFoundError（预期 RED） |
| RED-2 | bootstrap 契约（mock Popen/互斥/health） | `backend/tests/unit/test_kernel_bootstrap.py` | delegate_task（tdd-test-developer） | 同上 |
| RED-3 | CLI kernel status 契约 | `tests/cli/test_cli_kernel.py` | delegate_task（api-test-engineer） | 同上 |
| GREEN-1 | 错误类 + 状态文件层 | `infrastructure/kernel/kernel_errors.py` + `state.py` | Codex CLI | `pytest tests/unit/test_kernel_state.py tests/unit/test_kernel_version.py` 全绿 |
| GREEN-2 | ensure_kernel 实现 | `infrastructure/kernel/bootstrap.py` | Codex CLI | `pytest tests/unit/test_kernel_bootstrap.py` 全绿 |
| GREEN-3 | 包导出 + CLI 命令 | `infrastructure/kernel/__init__.py` + `cli/commands/kernel.py` | Codex CLI | `pytest ../tests/cli/test_cli_kernel.py` 全绿 |
| GREEN-4 | CLI 注册（MODIFY） | `cli/commands/__init__.py` + `cli/app.py` | Codex CLI | `inkflow kernel status` 可调用 |
| 登记 | ci.yml 追加 test_cli_kernel.py | `.github/workflows/ci.yml` | 主 agent（纯登记） | PyYAML 断言 job 列表含新文件 |
| QA | 全量回归 + 覆盖率 + lint/type + M5/M6 手工 | — | 主 agent | 见下 |

## 关键契约（RED docstring 必须钉住，GREEN 照此实现）

- `state.py`：`read_kernel_state(path) -> KernelState | None`（无/损坏 → None）、
  `write_kernel_state(path, payload)`（原子写：tmp + os.replace，复用 serve.py `_write_port_file` 模式）、
  `mark_stale(path) -> Path`（重命名 `kernel.json.stale-<ts>` 保留现场）、`KernelState`（port/token/pid/version/started_at）
- `bootstrap.py`：`async def ensure_kernel(*, spawn_cmd=None, timeout=30.0, health_timeout=2.0, state_file=None, version_check=True) -> KernelHandle`；
  装配缝：互斥获取（模块级函数，183 → 走轮询）、`subprocess.Popen`、health 探测（http 客户端）、
  `_default_spawn_cmd()`（sys.frozen 分支）
- `kernel_errors.py`：`KernelStartupError(Exception)`，消息含 `%TEMP%\inkflow-kernel.log` 指引
- CLI：`inkflow kernel status [--json]`——信封 `{"ok": true, "data": {...}}`，未运行 = `{"ok": true, "data": {"running": false}}` 退出码 0

## 完成门禁

- M1-M7（spec §13）全绿；覆盖率后端 98.5 行 / 95.0 分支（ADR-027）
- `uv run ruff check src/ tests/unit/ ../tests/ --no-cache` + mypy 通过
- ci.yml `integration-cli-backend` job 显式含 `test_cli_kernel.py`
- PR：`Closes #166`，Conventional Commits 标题（冒号后首字符小写）
- 合并前等全部 job（含第二批 coverage-backend），不要只盯 required
