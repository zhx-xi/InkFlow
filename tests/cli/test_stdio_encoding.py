"""CLI stdio 编码契约（#1240）— 真子进程 + **清空 PYTHONUTF8/PYTHONIOENCODING** 的 cp936 环境。

── 缺陷（v0.15.0-rc1 发布验证实测）──────────────────────────────────────────
中文 Windows（控制台代码页 936）下**打包版 CLI** 的 stdout 回落为 GBK：
重定向/管道被 UTF-8 工具读成乱码（journey 探针静默假红 #1175/#1179）。
根因两层（issue #1240 取证）：
  ① `cli/app.py` 无任何 stdio 编码归一 → 编码跟随控制台代码页（cp936）；
  ② `pyinstaller/inkflow.spec` 的 runtime hook 只 reconfigure(errors="replace")，
     **编码本身不动**（注释原文「不改动编码本身」）→ 冻结版固化 GBK。
dev 侧此前被 shell 里预设的 `PYTHONUTF8=1` 掩盖（实测：清掉后 `sys.flags.utf8_mode`
0→1、stdout `gbk`→`utf-8`）。故本契约**显式擦除**这两个变量，使断言**与环境无关**
——这正是 issue 验收判据 2 的形态。

── 为什么不在测试里直接 reconfigure 父进程 ────────────────────────────────
pytest 父进程的 sys.stdout 被 capture 包装，直接改会污染其他测试；子进程隔离。
子进程形态沿用既有先例 `tests/cli/test_cli_blackbox.py::_inkflow`（sys.executable
+ `-m inkflow`），但**不起真实内核**（`--help` 纯本地）→ 无需 skipif(CI)。

── MCP 不在本契约范围（实测证据，非推断）────────────────────────────────────
`mcp==2.0` 的 `mcp/server/stdio.py::stdio_server()` 已用 `encoding="utf-8"` 重新
包装 stdin/stdout 并接管 fd 0/1（源码注释：the std handles' platform encodings are
unreliable）→ MCP 协议帧本就不受代码页影响。若在 async 主循环里 reconfigure
sys.stdout，会与 `_claim_fd` 抢 fd、破坏已建立的 anyio 流。
"""

from __future__ import annotations

import os
import subprocess
import sys

# 环境无关性：必须钉死 cp936 现场（显式 PYTHONUTF8=0），否则父进程污染会掩盖缺陷
_CLEAR = ("PYTHONUTF8", "PYTHONIOENCODING")

_CN = "辅助小说创作工具"  # `inkflow --help` 标题中的中文（Typer 中文 help）


def _run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    """在**确定的 cp936 现场**跑真 CLI 子进程（bytes 捕获）。

    🔴 必须显式传 `PYTHONUTF8=0`，不能只擦除变量：
    同进程的 `tests/integration/test_data_dir_recovery.py` 会向 `os.environ` 注入
    `PYTHONUTF8=1`（全量跑时 pytest 自身 `utf8_mode=1`），而子进程继承的是
    **解释器启动态**而非当前 `os.environ` → 只擦除变量在本进程内失效。
    显式置 0 让本契约自足：无论父进程如何，子进程必为 cp936 现场。
    """
    env = {k: v for k, v in os.environ.items() if k not in _CLEAR}
    env["PYTHONUTF8"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "inkflow", *args],
        capture_output=True,
        timeout=90,
        env=env,
    )


def test_cli_stdout_is_utf8_without_env_utf8_flags() -> None:
    """判据 2（环境无关）：擦除 PYTHONUTF8/PYTHONIOENCODING 后，CLI stdout 仍为 UTF-8。

    🔴 RED 锚点：当前无任何 reconfigure → stdout 跟随控制台代码页 cp936
    → stdin/stdout 仍可解码但**判据 1/3 全红**（decode('utf-8') 抛 UnicodeDecodeError）。
    """
    proc = _run_cli("--help")
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    text = proc.stdout.decode("utf-8")  # RED：UnicodeDecodeError
    assert _CN in text, f"中文关键词 {_CN!r} 未在 UTF-8 解码结果中出现（疑乱码）"


def test_cli_stdout_bytes_decode_as_utf8() -> None:
    """判据 1（核心，纯 ASCII 版）：无中文的确定性输出同样 UTF-8 可解。

    🔴 RED 锚点：cp936 下 stdout 为 GBK 字节，UTF-8 解码抛 UnicodeDecodeError。
    """
    proc = _run_cli("--version")
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    text = proc.stdout.decode("utf-8")  # 失败即 RED（UnicodeDecodeError）
    assert text.startswith("InkFlow v"), f"版本输出形态异常: {text!r}"


def test_cli_chinese_output_roundtrips_as_utf8() -> None:
    """判据 1（含中文）+ 判据 5（重定向可解析）：中文输出 UTF-8 无损往返。

    🔴 RED 锚点：cp936 下 `帮助` 落盘为 GBK 双字节，UTF-8 解码失败/乱码。
    """
    proc = _run_cli("--help")
    text = proc.stdout.decode("utf-8")  # RED：UnicodeDecodeError
    assert _CN in text, f"中文关键词 {_CN!r} 未在 UTF-8 解码结果中出现（疑乱码）"


def test_cli_stderr_is_utf8_too() -> None:
    """判据 1 补充：stderr 同样归一（错误信封与人类模式错误走 stderr）。

    走 `--json` 误置全局选项路径（`cli/app.py::_JsonHintGroup.main` 的
    `typer.echo(err=True)`，纯本地、不触内核）产出中文 stderr。
    🔴 RED 锚点：cp936 下 stderr 为 GBK 且带 `❌` emoji 时仅 errors=replace 兜底。
    """
    proc = _run_cli("project", "list", "--json")
    assert proc.stderr, "stderr 为空，无法判定编码"
    proc.stderr.decode("utf-8")  # 失败即 RED（UnicodeDecodeError）
