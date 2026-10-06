"""#1388：内核日志混合编码根治 —— ``_spawn_kernel`` 强制子进程 IO 为 UTF-8。

背景（issue #1388 实测）：``%TEMP%\\inkflow-kernel.log`` 不是合法 UTF-8 ——
严格 UTF-8 读在首个非 ASCII 字节处 ``UnicodeDecodeError``（实测 918MB 文件在
211,593 字节处崩）。机制：**同一文件被两种编码写出**

| 写入方 | 编码 |
|---|---|
| 事件行 ``_log_kernel_event`` | UTF-8（显式 ``encoding="utf-8"``） |
| 内核 stdout/stderr（``_spawn_kernel`` 的 ``Popen``） | ANSI 代码页（简中 = CP936/GBK） |

修复 = ``Popen(..., env={**os.environ, "PYTHONIOENCODING": "utf-8"})``，
内核 stdout/stderr 改以 UTF-8 写出。

⚠️ **1.4 修订（#1477）改变了本契约的前提**：事件行与内核输出**已分文件**
（``inkflow-kernel-events.log`` vs ``inkflow-kernel-<kind>-<hash>.boot.log``，spec §6.2），
混编在结构上不再可能；但 ``PYTHONIOENCODING=utf-8`` 注入仍须保留（引导日志要是可读 UTF-8）。

RED 契约：

1. 平台无关锁定：Popen 的 ``env`` 显式含 ``PYTHONIOENCODING=utf-8``，
   且**保留** ``os.environ``（增量注入，不是替换）；
2. 真实复现：父侧 env 预置 ANSI 口径（``PYTHONIOENCODING=gbk``）时，内核输出仍须以 UTF-8
   写进**引导日志**、事件行以 UTF-8 写进**事件日志**，两份各自严格 UTF-8 可读；
3. 回归守护：stdout 仍指向日志句柄、stderr 仍合并进同一文件（顺序保持），
   creationflags 形态不变。

⚠️ 用例 2/3 走真实子进程 + ``tmp_path``（monkeypatch ``tempfile.gettempdir``），
**绝不碰真实 %TEMP%**。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from inkflow.infrastructure.kernel import bootstrap
from inkflow.infrastructure.kernel.bootstrap import (
    _log_kernel_event,
    _spawn_kernel,
    kernel_boot_log_path,
    kernel_event_log_path,
)


def _use_tmp_tempdir(monkeypatch, tmp_path: Path) -> None:
    """把内核日志目录指向 tmp_path（禁碰真实 %TEMP%，#1380 同款）。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))


def test_spawn_kernel_popen_forces_utf8_io_encoding(tmp_path, monkeypatch):
    """Popen 必须显式传 env（含 PYTHONIOENCODING=utf-8）且保留 os.environ。

    平台无关的锁定：不开真实子进程，直接检视装配缝；同时守护既有 kwargs 形态。
    """
    monkeypatch.setenv("INKFLOW_ENCODING_SENTINEL_1388", "sentinel-1388")
    popen = MagicMock()
    popen.poll.return_value = None
    log_file = tmp_path / "inkflow-kernel-dev-abc.boot.log"

    with patch.object(bootstrap.subprocess, "Popen", return_value=popen) as spawn_popen:
        _spawn_kernel([sys.executable, "-c", "pass"], log_file)

    spawn_popen.assert_called_once()
    _, kwargs = spawn_popen.call_args
    env = kwargs.get("env")
    assert env is not None, "Popen 未传 env → 内核 stdout 走 ANSI 代码页 → 日志不可读"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["INKFLOW_ENCODING_SENTINEL_1388"] == "sentinel-1388", (
        "env 须增量注入，不得替换 os.environ"
    )

    # 回归守护：stdout/stderr 装配与 creationflags 形态不变
    assert kwargs["stdout"] is not None
    assert kwargs["stderr"] == subprocess.STDOUT
    expected_flags = 0
    if sys.platform == "win32":
        expected_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    assert kwargs["creationflags"] == expected_flags


def test_kernel_output_and_event_lines_are_each_strict_utf8(tmp_path, monkeypatch):
    """真实复现：ANSI 口径下内核输出仍须 UTF-8 落**引导日志**，事件行落**事件日志**。

    父侧 env 预置 ``PYTHONIOENCODING=gbk`` 模拟 Windows 默认代码页；
    修复前子进程按 GBK 写出中文 → ``read_text(encoding="utf-8")`` 抛
    ``UnicodeDecodeError``（正是 issue 实测的排障面故障）。
    """
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    _use_tmp_tempdir(monkeypatch, tmp_path)
    boot_log = kernel_boot_log_path("dev", tmp_path / "kernel.json")

    _log_kernel_event("事件行-1388")  # 事件行落独立事件日志
    proc = _spawn_kernel(
        [sys.executable, "-c", "print('内核输出-1388-中文')"],
        boot_log,
    )
    proc.wait(timeout=60)

    boot_text = boot_log.read_text(encoding="utf-8")  # 非 UTF-8 则抛 UnicodeDecodeError
    assert "内核输出-1388-中文" in boot_text, "内核 stdout 未以 UTF-8 写出"
    assert "事件行-1388" not in boot_text, "1.4：事件行不得再混进内核输出文件"
    assert "事件行-1388" in kernel_event_log_path().read_text(encoding="utf-8")


def test_spawn_kernel_keeps_stderr_merged_into_same_file(tmp_path, monkeypatch):
    """回归守护：stdout 落日志句柄、stderr 合并（STDOUT）→ 两者都进同一份引导日志。

    ⚠️ 不断言 out/err 的**行序**：stdout 重定向到文件是块缓冲、stderr 无缓冲，
    真实次序由 Python 缓冲策略决定（实测 err 先于 out），与本次改动无关。
    """
    _use_tmp_tempdir(monkeypatch, tmp_path)
    boot_log = kernel_boot_log_path("dev", tmp_path / "kernel.json")
    script = "import sys; print('out-1388'); print('err-1388', file=sys.stderr)"

    proc = _spawn_kernel([sys.executable, "-c", script], boot_log)
    proc.wait(timeout=60)

    text = boot_log.read_text(encoding="utf-8")
    assert "out-1388" in text
    assert "err-1388" in text
