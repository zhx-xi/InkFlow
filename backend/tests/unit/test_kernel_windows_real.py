"""F30 装配缝真实实现测试（Windows）— 覆盖率补测（2026-08-07，QA 门禁）。

单元测试 mock 掉 bootstrap 装配缝导致其真实实现 0 覆盖（bootstrap.py 71.7%），
拖低全仓行覆盖率至 98.15% < 98.5%（ADR-027 门禁）。本文件直接调用真实实现
（不 mock），Windows 专用（CI/本机均为 Windows；非 Windows 跳过——POSIX 分支
由既有单测语义覆盖）。

覆盖目标（对照 coverage.xml miss 行）：
- _acquire_mutex 真实互斥（成功 / 183 / 释放后再获取）
- _release_mutex 真实释放
- _spawn_kernel 真实 Popen（CREATE_NO_WINDOW 子进程 + 日志文件）
- _probe_health 真实 HTTP（200 → True；连接拒绝 → False）
- _log_kernel_event 真实日志写
- _read_lenient 错误分支（非 dict / 缺字段 / 类型错 / started_at 非法）
"""

from __future__ import annotations

import http.server
import json
import socket
import subprocess
import sys
import threading
from datetime import datetime

import pytest

from inkflow.infrastructure.kernel.bootstrap import (
    _acquire_mutex,
    _log_kernel_event,
    _probe_health,
    _read_lenient,
    _release_mutex,
    _spawn_kernel,
)
from inkflow.infrastructure.kernel.state import KernelState

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="真实 Win32 互斥/Popen 语义仅 Windows"
)


def _free_port() -> int:
    """获取一个大概率空闲的端口（绑定后立即释放）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── _acquire_mutex / _release_mutex 真实互斥 ───────────────────────────


def test_acquire_mutex_success_and_release_reacquire():
    """真实 CreateMutexW：获取成功 → 释放 → 可再次获取（生命周期闭环）。"""
    h1 = _acquire_mutex("InkFlowTestMutex")
    assert h1 is not None
    _release_mutex(h1)
    h2 = _acquire_mutex("InkFlowTestMutex")
    assert h2 is not None  # 释放后互斥可重入（非 183）
    _release_mutex(h2)


def test_acquire_mutex_183_returns_none_when_held():
    """真实 CreateMutexW：同名互斥已持有 → 第二次获取返回 None（183）。"""
    h1 = _acquire_mutex("InkFlowTestMutex183")
    assert h1 is not None
    try:
        h2 = _acquire_mutex("InkFlowTestMutex183")
        assert h2 is None  # ERROR_ALREADY_EXISTS
    finally:
        _release_mutex(h1)


def test_release_mutex_none_is_noop():
    """_release_mutex(None) 不抛错（防御分支）。"""
    _release_mutex(None)


# ── _spawn_kernel 真实 Popen ───────────────────────────────────────────


def test_spawn_kernel_real_process_and_log_file(tmp_path):
    """真实 Popen：detach 子进程运行 + stdout 重定向到日志文件。"""
    log_file = tmp_path / "inkflow-kernel.log"
    proc = _spawn_kernel(
        [sys.executable, "-c", "import time; time.sleep(30)"], log_file
    )
    try:
        assert proc.pid > 0
        assert proc.poll() is None  # 进程存活（CREATE_NO_WINDOW detach）
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )
        proc.wait(timeout=10)


# ── _probe_health 真实 HTTP ────────────────────────────────────────────


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """固定 200 的 /health 探测 handler。"""

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # 静默访问日志
        pass


def test_probe_health_real_http_200():
    """真实 HTTP：监听 200 → True（带 X-InkFlow-Token 头）。"""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert _probe_health(port, "test-token", 2.0) is True
    finally:
        srv.shutdown()
        srv.server_close()


def test_probe_health_real_connection_refused():
    """真实 HTTP：未监听端口 → False（超时/异常兜底）。"""
    assert _probe_health(_free_port(), "test-token", 0.5) is False


# ── _log_kernel_event 真实日志写 ───────────────────────────────────────


def test_log_kernel_event_writes_file(tmp_path, monkeypatch):
    """真实日志：%TEMP%/inkflow-kernel.log 追加写含消息与时间戳。"""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    _log_kernel_event("test-event-123")
    log_file = tmp_path / "inkflow-kernel.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test-event-123" in content
    assert "[" in content  # 时间戳前缀


def test_log_kernel_event_oserror_is_silent(tmp_path, monkeypatch):
    """日志写入 OSError → 静默吞掉（不抛错，spec §6.2 排障日志容错）。"""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    def _raise(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _raise)
    _log_kernel_event("should-not-crash")  # 不抛 = 通过


def test_acquire_mutex_create_failure_returns_none(monkeypatch):
    """CreateMutexW 返回 NULL（内核对象创建失败）→ None（L56 分支）。"""
    import ctypes

    monkeypatch.setattr(
        ctypes.windll.kernel32, "CreateMutexW", lambda *a, **k: 0
    )
    assert _acquire_mutex("InkFlowTestMutexFail") is None


def test_is_process_alive_getexitcode_failure_returns_false(monkeypatch):
    """GetExitCodeProcess 失败 → False（state.py L121 分支，mock Win32 API）。"""
    import ctypes

    from inkflow.infrastructure.kernel.state import is_process_alive

    monkeypatch.setattr(
        ctypes.windll.kernel32, "GetExitCodeProcess", lambda *a, **k: 0
    )
    assert is_process_alive(12345) is False


# ── _read_lenient 错误分支（TestPollStateFile 只覆盖成功路径）──────────


def test_read_lenient_non_dict_json_returns_none(tmp_path):
    """JSON 非 dict（数组）→ None。"""
    path = tmp_path / "kernel.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _read_lenient(path) is None


def test_read_lenient_missing_field_returns_none(tmp_path):
    """缺字段（token 缺失）→ None。"""
    path = tmp_path / "kernel.json"
    path.write_text(
        json.dumps({"port": 8123, "pid": 12345, "version": "1.0.0"}),
        encoding="utf-8",
    )
    assert _read_lenient(path) is None


def test_read_lenient_type_mismatch_returns_none(tmp_path):
    """类型不符（port 为字符串）→ None。"""
    path = tmp_path / "kernel.json"
    path.write_text(
        json.dumps(
            {
                "port": "8123",
                "token": "tok",
                "pid": 12345,
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    assert _read_lenient(path) is None


@pytest.mark.parametrize(
    "bad_key,bad_value",
    [
        ("token", 123),  # token 非 str
        ("pid", "12345"),  # pid 非 int
        ("version", 1.0),  # version 非 str
    ],
)
def test_read_lenient_any_field_type_mismatch_returns_none(
    tmp_path, bad_key, bad_value
):
    """任一字段类型不符 → None（QA 补测：token/pid/version 类型分支）。"""
    path = tmp_path / "kernel.json"
    path.write_text(
        json.dumps(
            {
                "port": 8123,
                "token": "tok",
                "pid": 12345,
                "version": "1.0.0",
                bad_key: bad_value,
            }
        ),
        encoding="utf-8",
    )
    assert _read_lenient(path) is None


def test_read_lenient_invalid_started_at_falls_back_now(tmp_path):
    """四字段 + started_at 非法字符串 → 容忍并补当前 UTC（L156-159 分支）。"""
    path = tmp_path / "kernel.json"
    path.write_text(
        json.dumps(
            {
                "port": 8123,
                "token": "tok",
                "pid": 12345,
                "version": "1.0.0",
                "started_at": "not-a-timestamp",
            }
        ),
        encoding="utf-8",
    )
    st = _read_lenient(path)
    assert isinstance(st, KernelState)
    assert st.port == 8123
    assert isinstance(st.started_at, datetime)
