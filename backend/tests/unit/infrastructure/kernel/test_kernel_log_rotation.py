"""#1380 启动期归档 → #1477 1.4 修订：**客户端事件日志**的归档契约 + 内核运行日志分片。

背景（issue #1380 实测）：日志文件是**机器级共享**（CLI / GUI / 跑测试拉起的内核同写一份），
自 2026-08-07 累积至 **918MB / 421 万行 / 8826 次内核启动**，全文件无 size cap、
无 rotate、无启动期清理。修复 = 超限即归档（保留若干份，最旧被删）。

⚠️ **1.4 修订（#1477）改变了本文件的被测对象**：内核运行日志已改由内核自己持有句柄、
由现成日志库轮转（`test_kernel_logging.py`）；本文件现在测的是**客户端事件日志**
（`kernel_event_log_path()`，由客户端 append 后即 close，无长期持有者 ⇒ 既有「认领 + 归档链」
多进程安全设计**对它依然有效**，故完整保留 #1380 的全部契约）。

RED 契约（spec f30-kernel §6.2/§6.3）：

1. 超限归档：预置超限文件 → 入口调用 → 原内容**完整**落入 ``.1``，新文件从空开始；
2. 保留份数：多轮触发 → ``.1``/``.2`` 轮转，超出份数的最旧归档被删；
3. 未超限不动：小文件原样追加（不归档、不丢历史）；
4. spawn 前同样归档：内核 stdout/stderr 落进空的新文件；
5. 幂等 / 并发安全：并发调用不抛异常、不留半截（torn）文件、不丢事件行；
6. 归档失败不阻塞启动：目标被占用等 OSError → 静默跳过、原文件不截断。
7. **（1.4 新增）职责分离**：事件日志与内核运行日志是两个文件，且运行日志按 kind + data_dir 分片。

⚠️ 全部用例走 ``tmp_path`` + monkeypatch ``tempfile.gettempdir``，**绝不碰真实 %TEMP%**。
⚠️ 上限用 monkeypatch 压到字节级（生产常量须在**调用时**读取，见用例 1）——避免测试写 10MB。
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
    kernel_boot_log_path,
    kernel_event_log_path,
    kernel_runtime_log_path,
)

ARCHIVE_BLOCK = b"a" * 4096  # 「整块写入」标记：撕裂检测据此判定归档件是否被切断


def _use_tmp_tempdir(monkeypatch, tmp_path: Path) -> None:
    """把内核日志目录指向 tmp_path（禁碰真实 %TEMP%）。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))


def test_oversized_log_is_archived_and_restarts_empty(tmp_path, monkeypatch):
    """超限 → 归档为 .1（原内容完整），入口的下一次写入落在空的新文件里。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", len(ARCHIVE_BLOCK))
    log_file = kernel_event_log_path()
    log_file.write_bytes(ARCHIVE_BLOCK * 2)  # 2× 上限

    _log_kernel_event("oversized-1380")

    archived = tmp_path / "inkflow-kernel-events.log.1"
    assert archived.read_bytes() == ARCHIVE_BLOCK * 2, "原内容须完整归档（不得截断/丢失）"
    assert log_file.stat().st_size < len(ARCHIVE_BLOCK) * 2, "新文件须从空开始"
    assert "oversized-1380" in log_file.read_text(encoding="utf-8")
    assert not (tmp_path / "inkflow-kernel-events.log.2").exists(), "首次归档不产生 .2"


def test_only_n_backups_kept_oldest_dropped(tmp_path, monkeypatch):
    """多轮触发 → .1/.2 轮转；超出保留份数的最旧归档被删（总量有界）。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    cap = 16
    log_file = kernel_event_log_path()
    generations = bootstrap._KERNEL_LOG_BACKUPS + 2  # 触发次数 > 保留份数

    for generation in range(1, generations + 1):
        log_file.write_bytes(bytes([generation]) * 32)  # 32B > cap，逐代内容可辨识
        assert _rotate_kernel_log(log_file, max_bytes=cap) is True

    # 1.4：保留份数 2 → 10（对齐「单文件 10MB / 保留 10 份」默认）
    # ⚠️ 用集合比较：`.10` 按字符串排序会排在 `.2` 之前，列表比较会假红
    assert {p.name for p in tmp_path.iterdir()} == {
        f"inkflow-kernel-events.log.{index}"
        for index in range(1, bootstrap._KERNEL_LOG_BACKUPS + 1)
    }, "只保留 N 份（不得无限增长）"
    # 最旧被删（gen1..gen_{n-2} 消失），保留的是最近 N 代
    backup = bootstrap._KERNEL_LOG_BACKUPS
    assert (tmp_path / "inkflow-kernel-events.log.1").read_bytes() == bytes([generations]) * 32
    assert (tmp_path / f"inkflow-kernel-events.log.{backup}").read_bytes() == bytes(
        [generations - backup + 1]
    ) * 32


def test_small_log_appends_without_rotation(tmp_path, monkeypatch):
    """未超限 → 原样追加，不产生归档件（避免无谓 I/O 与历史丢失）。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    log_file = kernel_event_log_path()
    log_file.write_text("[2026-09-22T00:00:00] 前一条事件\n", encoding="utf-8")

    assert _rotate_kernel_log(log_file) is False
    _log_kernel_event("small-1380")

    assert not (tmp_path / "inkflow-kernel-events.log.1").exists()
    content = log_file.read_text(encoding="utf-8")
    assert content.startswith("[2026-09-22T00:00:00] 前一条事件\n"), "既有内容须保留"
    assert "small-1380" in content


def test_spawn_kernel_rotates_oversized_log_before_redirect(tmp_path, monkeypatch):
    """spawn 前同样归档：内核 stdout/stderr 才会落进空的**引导日志**（spec §6.2/§6.3）。

    1.4：`_spawn_kernel` 的重定向目标已从内核运行日志改为**引导日志**（前者由内核自持句柄，
    两个写者会导致库轮转必然失败）。
    """
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", len(ARCHIVE_BLOCK))
    log_file = kernel_boot_log_path("dev", tmp_path / "kernel.json")
    log_file.write_bytes(ARCHIVE_BLOCK * 2)

    proc = _spawn_kernel([sys.executable, "-c", "print('kernel-stdout-1380')"], log_file)
    proc.wait(timeout=30)

    assert Path(f"{log_file}.1").read_bytes() == ARCHIVE_BLOCK * 2
    assert "kernel-stdout-1380" in log_file.read_text(encoding="utf-8")


def test_concurrent_rotation_then_append_is_safe(tmp_path, monkeypatch):
    """并发 / 幂等：多内核同时启动的竞态下不抛异常、不撕裂、不丢事件行。

    阶段 A：8 线程同时归档同一份超限文件（无其它写句柄 → 归档必发生且整块完整）；
    阶段 B：8 线程并发追加事件（上限抬高，避免归档打断断言行数统计）。
    """
    _use_tmp_tempdir(monkeypatch, tmp_path)
    monkeypatch.setattr(bootstrap, "_KERNEL_LOG_MAX_BYTES", 64)
    log_file = kernel_event_log_path()
    log_file.write_bytes(ARCHIVE_BLOCK)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_rotate_kernel_log, log_file) for _ in range(8)]
        for future in futures:
            future.result()  # 任一 worker 抛异常 → 用例失败

    archived = tmp_path / "inkflow-kernel-events.log.1"
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
    log_file = kernel_event_log_path()
    log_file.write_bytes(b"b" * 64)

    def _raise(*_args, **_kwargs):
        raise OSError("归档目标被占用")

    monkeypatch.setattr(bootstrap.os, "replace", _raise)

    assert _rotate_kernel_log(log_file) is False  # 不抛，返回「未轮转」
    assert log_file.read_bytes() == b"b" * 64, "归档失败不得截断原文件"
    _log_kernel_event("still-works")  # 启动链路继续
    assert "still-works" in log_file.read_text(encoding="utf-8")


def test_runtime_log_path_partitions_by_kind_and_data_dir(tmp_path):
    """1.4：内核运行日志按 kind + data_dir 分片（spec §6.2/§6.3）。

    不分片则多内核（多 worktree / 多数据目录并存）会争抢同一文件 ⇒ 库轮转必败。
    """
    dev_a = kernel_runtime_log_path("dev", tmp_path / "a" / "kernel.json")
    dev_b = kernel_runtime_log_path("dev", tmp_path / "b" / "kernel.json")
    prod_a = kernel_runtime_log_path("prod", tmp_path / "a" / "kernel.json")

    assert dev_a != dev_b, "不同 data_dir 必须分片"
    assert dev_a != prod_a, "不同 kind 必须分片"
    assert dev_a == kernel_runtime_log_path("dev", tmp_path / "a" / "kernel.json"), "同输入须稳定"
    assert dev_a.name.startswith("inkflow-kernel-dev-")
    assert dev_a.name.endswith(".log")
    assert kernel_boot_log_path("dev", tmp_path / "a" / "kernel.json").name.endswith(".boot.log")


def test_event_log_is_separate_from_runtime_log(tmp_path, monkeypatch):
    """1.4：客户端事件行写**事件日志**，与内核运行日志不混装（spec §6.2 职责分离）。"""
    _use_tmp_tempdir(monkeypatch, tmp_path)
    _log_kernel_event("evt-1477")

    event_log = kernel_event_log_path()
    assert event_log.name == "inkflow-kernel-events.log"
    assert "evt-1477" in event_log.read_text(encoding="utf-8")
    runtime_log = kernel_runtime_log_path("dev", tmp_path / "kernel.json")
    assert runtime_log != event_log
    assert not runtime_log.exists(), "事件行不得写入内核运行日志"
