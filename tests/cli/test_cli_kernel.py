"""InkFlow kernel CLI 命令测试 — F30 内核冷启动基建（Issue #166，RED 阶段测试契约）.

覆盖 dev 调试命令 `inkflow kernel status`（spec §4：非用户面、帮助文本标注 dev）的
信封格式（F7 约定）/ 退出码 / 未运行语义。测试**绝不**真实拉起内核进程。

── GREEN 实现契约（backend/src/inkflow/cli/commands/kernel.py 必须满足）────────

1. 模块与命令签名：
   - 模块级 `app = typer.Typer(name="kernel", help=<帮助文本，必须含 dev 标注>,
     no_args_is_help=True)`；`status` 为其子命令。
   - **必须**提供空 callback（`@app.callback()`，不得覆盖 ctx.obj）——typer 0.27
     对「单命令 + 无 callback」的 Typer 组做压平（命令即组本身，`["status"]` 变
     用法错误 exit 2，实测 typer 0.27.0）；有 callback 后 `invoke(app, ["status"])`
     与本文件 invoke 形态成立，根面 `inkflow kernel status`（spec §4 字面）亦成立。
   - 命令 `status(ctx: typer.Context, ...)`（无额外必选参数）：读状态文件
     → pid 存活判定 → 输出。**绝不 spawn 内核进程**（纯查询，无任何拉起逻辑）。

2. 状态读取与 patch 注入点（本文件采用「源头模块」方案）：
   - 状态读取复用 `inkflow.infrastructure.kernel.state`（spec §8 state.py）：
     `read_kernel_state(state_file: Path) -> KernelState | None`（None = 无状态文件 /
     JSON 解析失败，spec §2.1 读取规则）与 `is_process_alive(pid: int) -> bool`。
     ⚠️ 父侧裁定（2026-08-07）：read_kernel_state 返回 **KernelState**（frozen
     dataclass，五字段属性访问 port/token/pid/version/started_at）而非 dict——
     与 test_kernel_state.py 契约一致；本文件 mock 返回 SimpleNamespace 模拟
     属性访问形态。
   - 命令必须经**模块属性访问**形态调用（`state.read_kernel_state(...)` /
     `state.is_process_alive(...)`）；**禁止**模块级 from-import 绑定这两个函数名
     （from-import 陷阱：patch 源头模块不生效）。
   - 本文件 patch 目标 = 源头模块（常量 STATE_MOD）：
     `inkflow.infrastructure.kernel.state.read_kernel_state` 与
     `inkflow.infrastructure.kernel.state.is_process_alive`。
   - 设计假设（spec 未逐字给定）：两函数为单参形态 (state_file) / (pid)，
     用例②断言调用参数（状态文件路径与 pid）。

3. config.data_dir 定位（本文件采用的方案，先例 test_cli_config.py）：
   - 命令从 `inkflow.core.config.config.data_dir`（共享实例属性）读取目录，
     状态文件路径 = `config.data_dir / "kernel.json"`（spec §6.1）。
   - 测试以 `monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)`
     重定向；用例①与④未运行分支走**真实读取路径**（tmp_path 下无 kernel.json，
     read_kernel_state 返回 None），用例②③ mock 读取函数。

4. --json 输出信封（ctx.obj.json_output=True 时，经 inkflow.cli.output.print_result）：
   - 运行中 → {"ok": true, "data": {"running": true, "pid": <int>, "port": <int>,
     "version": <str>}}（pid/port/version 来自状态文件原样透传）；
   - 未运行（无状态文件 / 损坏 / pid 已死）→ {"ok": true, "data": {"running": false}}；
   - **两种状态退出码均为 0**——状态查询不因未运行而失败（spec §4）。

5. 人类可读模式（ctx.obj.json_output=False）：
   - 运行中：文本含 PID / 端口 / 版本（用例④断言三值出现）；
   - 未运行：文本含「未运行」提示；退出码 0。

── RED 形态说明 ─────────────────────────────────────────
本文件顶部 import 尚未实现的 `inkflow.cli.commands.kernel` → 收集期
ModuleNotFoundError（`collected 0 items / 1 error`，pytest exit 2）——
全新模块整组 RED 的预期形态；GREEN 落地后整文件自动收集转绿。

⚠️ import 排序说明：RED 阶段 ruff 因 kernel 模块不可解析将其归类 third-party
（故 `from inkflow.cli.commands.kernel import app` 位于 pytest 与 typer 之间）；
GREEN 落地后 ruff 会重新归类 first-party 并报一次 I001——`ruff check --fix`
机械修复即可，不影响测试语义。

── 测试约定 ──────────────────────────────────────────────
- 所有 CliRunner 用 CliRunner(env={"NO_COLOR": "1"})：CI 设 FORCE_COLOR 时
  typer/rich 注入 ANSI 色码污染 output 断言（先例 test_cli_serve.py）。
- --json 语义经 invoke(..., obj=CliContext(json_output=True)) 注入（先例
  test_cli_config.py / test_cli_character_errors.py）——status 从
  ctx.obj.json_output 分支输出，与根 app 全局 --json 选项同一语义。
- invoke 形态：`invoke(app, ["status"], ...)`（kernel app 直接调用，先例
  test_cli_config.py）；依赖 §1 的 callback 防压平契约（typer 0.27 单命令组
  无 callback 时 `["status"]` 为用法错误 exit 2）。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from inkflow.cli.commands.kernel import app
from typer.testing import CliRunner

from inkflow.cli.context import CliContext

# inkflow.core 包把 config 属性重绑定为实例，`import a.b as x` 会取到实例而非模块，
# 因此用 importlib 取 sys.modules 中的真实模块（先例 test_cli_config.py）
core_config_mod = importlib.import_module("inkflow.core.config")

# patch 注入点 = 源头模块（见文件头 GREEN 实现契约 §2）：
# 命令必须以模块属性访问形态调用 state.read_kernel_state / state.is_process_alive
STATE_MOD = "inkflow.infrastructure.kernel.state"

# 模拟 kernel.json 合法内容（spec §2.1 五字段；pid/port/version 会被 status 透传）
RUNNING_STATE = {
    "port": 38291,
    "token": "test-token-abc123",
    "pid": 4242,
    "version": "0.1.0",
    "started_at": "2026-08-07T00:00:00+00:00",
}


@pytest.fixture
def cli_runner():
    # CI FORCE_COLOR 陷阱：NO_COLOR 强制关色，防 ANSI 码污染 output 断言（先例 test_cli_serve.py）
    return CliRunner(env={"NO_COLOR": "1"})


class TestKernelStatus:
    """inkflow kernel status：信封 / 退出码 / 未运行语义（spec §4 + F7 约定）。"""

    def test_status_not_running_no_state_file(self, cli_runner, tmp_path, monkeypatch):
        """无 kernel.json（真实读取路径）：--json → ok:true + running:false + exit 0."""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        result = cli_runner.invoke(app, ["status"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"running": False}

    def test_status_running_json(self, cli_runner, tmp_path, monkeypatch):
        """状态文件合法 + pid 存活：--json → running:true + pid/port/version 透传 + exit 0."""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        with (
            patch(
                f"{STATE_MOD}.read_kernel_state",
                return_value=SimpleNamespace(**RUNNING_STATE),
            ) as mock_read,
            patch(f"{STATE_MOD}.is_process_alive", return_value=True) as mock_alive,
            patch("subprocess.Popen") as mock_popen,
        ):
            result = cli_runner.invoke(app, ["status"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {
            "running": True,
            "pid": RUNNING_STATE["pid"],
            "port": RUNNING_STATE["port"],
            "version": RUNNING_STATE["version"],
        }
        # 读取契约：状态文件路径 = config.data_dir / "kernel.json"；存活判定用状态文件 pid
        mock_read.assert_called_once_with(tmp_path / "kernel.json")
        mock_alive.assert_called_once_with(RUNNING_STATE["pid"])
        # 只查询绝不拉起内核（spec §4）：status 不触碰任何 spawn 机制
        mock_popen.assert_not_called()

    def test_status_stale_pid_dead(self, cli_runner, tmp_path, monkeypatch):
        """状态文件存在但 pid 已死：--json → running:false + exit 0（不因未运行而失败）."""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        with (
            patch(
                f"{STATE_MOD}.read_kernel_state",
                return_value=SimpleNamespace(**RUNNING_STATE),
            ),
            patch(f"{STATE_MOD}.is_process_alive", return_value=False),
        ):
            result = cli_runner.invoke(app, ["status"], obj=CliContext(json_output=True))
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"] == {"running": False}

    def test_status_human_readable(self, cli_runner, tmp_path, monkeypatch):
        """人类模式：运行中 → 文本含 PID/端口/版本；未运行 → 「未运行」提示；均 exit 0."""
        monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
        # 运行中分支
        with (
            patch(
                f"{STATE_MOD}.read_kernel_state",
                return_value=SimpleNamespace(**RUNNING_STATE),
            ),
            patch(f"{STATE_MOD}.is_process_alive", return_value=True),
        ):
            result = cli_runner.invoke(app, ["status"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert str(RUNNING_STATE["pid"]) in result.output
        assert str(RUNNING_STATE["port"]) in result.output
        assert RUNNING_STATE["version"] in result.output
        # 未运行分支（真实读取路径：tmp_path 下无 kernel.json）
        result = cli_runner.invoke(app, ["status"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "未运行" in result.output
