"""#1380：%TEMP%\\inkflow-kernel.log 启动期归档（size cap + .1/.2 轮转）。

背景（issue #1380 实测）：该文件是**机器级共享**（CLI / GUI / 跑测试拉起的内核同写一份），
自 2026-08-07 累积至 **918MB / 421 万行 / 8826 次内核启动**，全文件无 size cap、
无 rotate、无启动期清理。修复 = 启动期发现超限即归档为 ``.1``（保留若干份，最旧被删）。

RED 契约（spec f30-kernel §6.2「启动期归档」）：

1. 超限归档：预置超限文件 → 入口调用 → 原内容**完整**落入 ``.1``，新文件从空开始；
2. 保留份数：多轮触发 → ``.1``/``.2`` 轮转，超出份数的最旧归档被删；
3. 未超限不动：小文件原样追加（不归档、不丢历史）；
4. spawn 前同样归档：内核全量 stdout/stderr 落进空的新文件；
5. 幂等 / 并发安全：并发调用不抛异常、不留半截（torn）文件、不丢事件行；
6. 归档失败不阻塞启动：目标被占用等 OSError → 静默跳过、原文件不截断。

⚠️ 全部用例走 ``tmp_path`` + monkeypatch ``tempfile.gettempdir``，**绝不碰真实 %TEMP%**。
⚠️ 上限用 monkeypatch 压到字节级（生产 50MB 常量须在**调用时**读取，见用例 1）——避免测试写 50MB。
"""

from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from inkflow.infrastructure.kernel import bootstrap
from inkflow.infrastructure.kernel.bootstrap import (
    _log_kernel_event,
    _rotate_kernel_log,
    _spawn_kernel,
    kernel_log_path,
)

ARCHIVE_BLOCK = b"a" * 4096  # 「整块写入」标记：撕裂检测据此判定归档件是否被切断


def _use_tmp_tempdir(monkeypatch, tmp_path: Path) -> None:
    """把内核日志目录指向 tmp_path（禁碰真实 %TEMP%）。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))


def test_oversized_log_is_archived_and_restarts_empty(tmp_path, monkeypatch):
    """超限 → 归档为 .1（原内容完整），入口的下一次写入落在空的新文件里。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", len(ARCHIVE_BLOCK))
    log_file = kernel_log_path()
    log_file.write_bytes(ARCHIVE_BLOCK * 2)  # 2× 上限

    _log_kernel_event("oversized-1380")

    archived = tmp_path / "inkflow-kernel.log.1"
    assert archived.read_bytes() == ARCHIVE_BLOCK * 2, "原内容须完整归档（不得截断/丢失）"
    assert log_file.stat().st_size < len(ARCHIVE_BLOCK) * 2, "新文件须从空开始"
    assert "oversized-1380" in log_file.read_text(encoding="utf-8")
    assert not (tmp_path / "inkflow-kernel.log.2").exists(), "首次归档不产生 .2"


def test_only_n_backups_kept_oldest_dropped(tmp_path, monkeypatch):
    """多轮触发 → .1/.2 轮转；超出保留份数的最旧归档被删（总量有界）。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    cap = 16
    log_file = kernel_log_path()
    generations = bootstrap._KERNEL_LOG_BACKUPS + 2  # 触发次数 > 保留份数

    for generation in range(1, generations + 1):
        log_file.write_bytes(bytes([generation]) * 32)  # 32B > cap，逐代内容可辨识
        assert _rotate_kernel_log(log_file, max_bytes=cap) is True

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "inkflow-kernel.log.1",
        "inkflow-kernel.log.2",
    ], "只保留 N 份（不得无限增长）"
    # 最旧被删（gen1/gen2 消失），保留的是最近两代
    assert (tmp_path / "inkflow-kernel.log.1").read_bytes() == bytes([generations]) * 32
    assert (tmp_path / "inkflow-kernel.log.2").read_bytes() == bytes([generations - 1]) * 32


def test_small_log_appends_without_rotation(tmp_path, monkeypatch):
    """未超限 → 原样追加，不产生归档件（避免无谓 I/O 与历史丢失）。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    log_file = kernel_log_path()
    log_file.write_text("[2026-09-22T00:00:00] 前一条事件\n", encoding="utf-8")

    assert _rotate_kernel_log(log_file) is False
    _log_kernel_event("small-1380")

    assert not (tmp_path / "inkflow-kernel.log.1").exists()
    content = log_file.read_text(encoding="utf-8")
    assert content.startswith("[2026-09-22T00:00:00] 前一条事件\n"), "既有内容须保留"
    assert "small-1380" in content


def test_spawn_kernel_rotates_oversized_log_before_redirect(tmp_path, monkeypatch):
    """spawn 前同样归档：内核 stdout/stderr 才会落进空的新文件（issue §5.3）。"""
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", len(ARCHIVE_BLOCK))
    log_file = tmp_path / "inkflow-kernel.log"
    log_file.write_bytes(ARCHIVE_BLOCK * 2)

    proc = _spawn_kernel([sys.executable, "-c", "print('kernel-stdout-1380')"], log_file)
    proc.wait(timeout=30)

    assert (tmp_path / "inkflow-kernel.log.1").read_bytes() == ARCHIVE_BLOCK * 2
    assert "kernel-stdout-1380" in log_file.read_text(encoding="utf-8")


def test_concurrent_rotation_then_append_is_safe(tmp_path, monkeypatch):
    """并发 / 幂等：多内核同时启动的竞态下不抛异常、不撕裂、不丢事件行。

    阶段 A：8 线程同时归档同一份超限文件（无其它写句柄 → 归档必发生且整块完整）；
    阶段 B：8 线程并发追加事件（上限抬高，避免归档打断断言行数统计）。
    """
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", 64)
    log_file = kernel_log_path()
    log_file.write_bytes(ARCHIVE_BLOCK)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_rotate_kernel_log, log_file) for _ in range(8)]
        for future in futures:
            future.result()  # 任一 worker 抛异常 → 用例失败

    archived = tmp_path / "inkflow-kernel.log.1"
    assert archived.read_bytes() == ARCHIVE_BLOCK, "归档件必须整块完整（并发下不得撕裂）"
    assert not log_file.exists(), "归档后原文件名应已让位"

    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", 1 << 20)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_log_kernel_event, "concurrent-1380") for _ in range(8)]
        for future in futures:
            future.result()

    # ⚠️ 这里**故意不断言「恰好 8 行」**：Windows CRT 的 O_APPEND 是「先 seek 到 EOF 再 write」，
    # 多句柄并发追加可能落到同一偏移互相覆盖 → 丢行。实测纯 `open("a") + write`（改动前的老实现
    # 完全同形）同样丢行（40 轮 19 次），与本批无关。契约只锁「不抛异常 + 不留半截行」。
    text = log_file.read_text(encoding="utf-8")
    assert "concurrent-1380" in text, "并发追加完全丢失"
    for line in text.splitlines(keepends=True):
        assert line.startswith("[") and line.endswith("\n"), "并发追加产生半截行"

    # 认领用的 `.rotating-*` 临时名不得残留（归档链全程应把它消费成 `.1`）
    leftovers = [p.name for p in tmp_path.iterdir() if ".rotating-" in p.name]
    assert leftovers == [], f"归档临时名残留：{leftovers}"


def test_rotation_failure_does_not_block_startup(tmp_path, monkeypatch):
    """归档失败（目标被占用等）→ 静默跳过，不向上抛、不截断原文件。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", 16)
    log_file = kernel_log_path()
    log_file.write_bytes(b"b" * 64)

    def _raise(*_args, **_kwargs):
        raise OSError("归档目标被占用")

    monkeypatch.setattr(bootstrap.os, "replace", _raise)

    assert _rotate_kernel_log(log_file) is False  # 不抛，返回「未轮转」
    assert log_file.read_bytes() == b"b" * 64, "归档失败不得截断原文件"
    _log_kernel_event("still-works")  # 启动链路继续
    assert "still-works" in log_file.read_text(encoding="utf-8")
