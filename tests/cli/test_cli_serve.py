"""Serve CLI 命令测试 — #77 内核进程化强化（RED 阶段测试契约）.

本文件整体重写 tests/cli/test_cli_serve.py：mock 目标从 `uvicorn.run` 升级为 serve
命令暴露的**装配缝 / 交付缝**（见下），并把 #77 新增契约（--port 0 动态端口、
--port-file 端口文件、--token、INKFLOW_READY 交付行、INKFLOW_SERVER_TOKEN env 注入、
--reload 与交付契约互斥）钉为可执行断言。测试**绝不**真实启动 uvicorn、绝不绑定端口。

── GREEN 实现契约（backend/src/inkflow/cli/commands/serve.py 必须满足）────────

1. 入口（保留现状）：
   - 模块级 `app = typer.Typer(name="serve", help=..., no_args_is_help=True)`；
     typer 0.27 将「单命令 + 无 callback」的 Typer 组压平为命令本身，
     故 `CliRunner().invoke(app, [])` 即执行 serve，无需 "serve" 子命令参数。
   - 命令函数仍名为 `serve`，完整签名（Typer 参数）：
       serve(
           host: str = typer.Option("127.0.0.1", "--host", "-H"),
           port: int = typer.Option(8000, "--port", "-p"),
           port_file: Path | None = typer.Option(None, "--port-file"),
           token: str | None = typer.Option(None, "--token"),
           open_browser: bool = typer.Option(False, "--open-browser"),
           reload: bool = typer.Option(False, "--reload"),
       )
   - `port_file` 必须注解为 pathlib.Path | None（Typer 自动转 Path；None = 不写文件）。
   - `--port 0` 保持 int 语义原样传递（新语义：系统动态分配端口，spec §2.2）。

2. 装配缝 `_run_server(host: str, port: int, reload: bool) -> int`（模块级函数）：
   - 职责：手动装配 uvicorn（uvicorn.Config + uvicorn.Server，**不得**用 uvicorn.run
     快捷函数），阻塞运行直至服务退出；返回**实际监听端口**（int）——`--port 0` 时
     返回系统分配的真实端口（如从 server.servers[0].sockets[0].getsockname()[1] 读取）。
   - serve 在 reload 与非 reload 模式下**都**经此函数启动（reload=True 传参），
     禁止 serve 内部另走 uvicorn.run 路径——本文件所有用例只 patch 这一处装配缝。
   - reload 模式下返回值无意义（serve 不使用交付，见 5）。

3. 交付缝 `_write_port_file(path: Path, payload: dict) -> None`（模块级函数）：
   - 职责：把 payload（JSON 可序列化 dict）原子写入 path（先写临时文件再 os.replace，
     防壳读到半截 JSON，spec §2.1.2）。仅在 `--port-file` 显式指定且非 reload 时
     被 serve 调用；缺省不调用（stdout 是唯一默认交付通道，spec §2.1.2 Q1）。

4. env 注入（时序契约）：serve 在调用 `_run_server` **之前**执行
   `os.environ["INKFLOW_SERVER_TOKEN"] = <token>`——reload 模式同样注入
   （reload 子进程经 env 继承 token，校验保持启用不降级，spec §2.2 Q3）。
   token 解析：
   - `--token TOKEN` 显式 → 原样使用；
   - 缺省 → `secrets.token_urlsafe(32)` 随机生成（spec §2.2；本文件只断言非空 + 每次不同）。

5. 交付行（非 reload 模式）：_run_server 返回后（= 服务启动完成），serve 向 stdout
   输出**恰好一次** `INKFLOW_READY {json}` 单行（typer.echo/print 皆可，CliRunner 捕获）：
       INKFLOW_READY {"port": <实际端口>, "token": <token>, "pid": <os.getpid()>,
                      "version": <inkflow.__version__>}
   - port 必须取 _run_server **返回值**（动态端口语义），不是请求端口；
   - version 读 `inkflow.__version__` 模块属性（现 0.1.0；**不得硬编码版本号**，
     里程碑升级时测试自动跟随）；
   - reload 模式：**不输出** INKFLOW_READY、不写端口文件（与交付契约互斥）。

6. 启动提示：无论 reload 与否，serve 先输出含 "🚀" 的启动提示行（非交付行）。

7. --open-browser（保留原测试意图）：注册
   `threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}/docs"))`，
   不立即打开浏览器（Timer 触发时才开）。

8. 端口文件 payload 与 INKFLOW_READY 行 JSON **完全一致**（spec §2.1.1/§2.1.2 M1：
   文件内容一致），四键 port/token/pid/version。

── 测试约定 ──────────────────────────────────────────────
- 所有 CliRunner 用 `CliRunner(env={"NO_COLOR": "1"})`：CI 设 FORCE_COLOR 时
  typer/rich 会注入 ANSI 色码污染 output 断言，NO_COLOR 强制关色。
- serve 会向进程 env 注入 INKFLOW_SERVER_TOKEN，autouse fixture 在用例后恢复原值，
  防用例间污染。
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from inkflow import __version__

SERVE_MOD = "inkflow.cli.commands.serve"
# _run_server 的 mock 返回值：模拟「--port 0 动态分配到的实际端口」
FAKE_PORT = 38291


def _param(call, name: str, pos: int):
    """取调用参数：优先 kwargs[name]，否则按位置 args[pos]（兼容两种调用风格）."""
    if name in call.kwargs:
        return call.kwargs[name]
    return call.args[pos]


def _parse_ready(output: str) -> dict:
    """从 CLI 输出解析 INKFLOW_READY 交付行，断言恰好出现一次且为单行 JSON."""
    lines = [ln for ln in output.splitlines() if ln.startswith("INKFLOW_READY ")]
    assert (
        len(lines) == 1
    ), f"INKFLOW_READY 交付行应恰好输出一次，实际 {len(lines)} 行。输出: {output!r}"
    return json.loads(lines[0][len("INKFLOW_READY ") :])


@pytest.fixture
def cli_runner():
    # CI FORCE_COLOR 陷阱：强制 NO_COLOR 关色，避免 ANSI 码污染 output 断言
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def _restore_server_token_env(monkeypatch):
    """serve 命令会向进程 env 注入 INKFLOW_SERVER_TOKEN；用例结束后恢复原值."""
    yield
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)


class TestServeArgs:
    """装配缝调用参数契约（_run_server 收到什么）."""

    def test_serve_defaults(self, cli_runner):
        """serve 默认参数：_run_server(host="127.0.0.1", port=8000, reload=False)."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT) as mock_run:
            result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call = mock_run.call_args
        assert _param(call, "host", 0) == "127.0.0.1"
        assert _param(call, "port", 1) == 8000
        assert _param(call, "reload", 2) is False
        # 启动提示（非交付行）仍输出
        assert "🚀" in result.output

    def test_serve_custom_host_port(self, cli_runner):
        """serve --host/--port：自定义值原样传入装配缝."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT) as mock_run:
            result = cli_runner.invoke(app, ["--host", "0.0.0.0", "--port", "9999"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call = mock_run.call_args
        assert _param(call, "host", 0) == "0.0.0.0"
        assert _param(call, "port", 1) == 9999

    def test_serve_port_zero_dynamic(self, cli_runner):
        """--port 0：0 原样传入装配缝（动态分配语义）；交付行 port 为实际端口."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT) as mock_run:
            result = cli_runner.invoke(app, ["--port", "0"])
        assert result.exit_code == 0
        assert _param(mock_run.call_args, "port", 1) == 0
        # 交付行 port 必须来自 _run_server 返回值，而非请求端口 0
        assert _parse_ready(result.output)["port"] == FAKE_PORT


class TestServeDelivery:
    """交付契约（INKFLOW_READY 行 + 端口文件 + env 注入 + reload 互斥）."""

    def test_serve_ready_line_format(self, cli_runner):
        """INKFLOW_READY 交付行：单行 JSON，四键 port/token/pid/version 齐全且语义正确."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        payload = _parse_ready(result.output)
        assert set(payload) == {"port", "token", "pid", "version"}
        assert payload["port"] == FAKE_PORT  # 实际端口来自 _run_server 返回值
        assert payload["pid"] == os.getpid()  # 内核进程 PID（壳做健康监控/回收）
        assert payload["version"] == __version__  # 版本来自 inkflow.__version__
        assert isinstance(payload["token"], str) and payload["token"]

    def test_serve_explicit_token(self, cli_runner):
        """--token ABC：env 注入与交付行 token 均使用显式值."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result = cli_runner.invoke(app, ["--token", "ABC"])
        assert result.exit_code == 0
        assert os.environ["INKFLOW_SERVER_TOKEN"] == "ABC"
        assert _parse_ready(result.output)["token"] == "ABC"

    def test_serve_default_token_random(self, cli_runner):
        """缺省 --token：随机生成非空 token，且 env 注入的就是交付行中的 token."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        token = _parse_ready(result.output)["token"]
        assert isinstance(token, str) and token  # 非空（随机生成）
        assert os.environ["INKFLOW_SERVER_TOKEN"] == token  # env 注入的是使用中的 token

    def test_serve_default_token_is_random_per_start(self, cli_runner):
        """缺省 token 每次启动随机：两次调用生成不同 token（spec §2.2「每次启动随机」）."""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result1 = cli_runner.invoke(app, [])
        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result2 = cli_runner.invoke(app, [])
        token1 = _parse_ready(result1.output)["token"]
        token2 = _parse_ready(result2.output)["token"]
        assert token1 and token2
        assert token1 != token2

    def test_serve_port_file_written(self, cli_runner, tmp_path):
        """--port-file PATH：交付缝被调用，路径=PATH，payload 与 INKFLOW_READY 行一致."""
        from inkflow.cli.commands.serve import app

        port_file = tmp_path / "serve.json"
        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch(f"{SERVE_MOD}._write_port_file") as mock_write,
        ):
            result = cli_runner.invoke(app, ["--port-file", str(port_file)])
        assert result.exit_code == 0
        mock_write.assert_called_once()
        call = mock_write.call_args
        # 路径契约：port_file 选项注解为 Path，交付缝收到 pathlib.Path
        assert _param(call, "path", 0) == port_file
        payload = _param(call, "payload", 1)
        assert set(payload) == {"port", "token", "pid", "version"}
        # spec M1：端口文件内容与 stdout 交付行一致
        assert payload == _parse_ready(result.output)

    def test_serve_no_port_file_by_default(self, cli_runner):
        """缺省 --port-file：不写端口文件（stdout 是唯一默认交付通道）."""
        from inkflow.cli.commands.serve import app

        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch(f"{SERVE_MOD}._write_port_file") as mock_write,
        ):
            result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        mock_write.assert_not_called()

    def test_serve_reload_no_delivery(self, cli_runner, tmp_path):
        """--reload：不输出 INKFLOW_READY、不写端口文件；token env 仍注入（校验不降级）."""
        from inkflow.cli.commands.serve import app

        port_file = tmp_path / "serve.json"
        env_seen = {}

        def _fake_run(host, port, reload):
            # 时序契约：env 注入必须先于服务器启动（reload 子进程经 env 继承 token）
            env_seen["token"] = os.environ.get("INKFLOW_SERVER_TOKEN")
            return 0

        with (
            patch(f"{SERVE_MOD}._run_server", side_effect=_fake_run) as mock_run,
            patch(f"{SERVE_MOD}._write_port_file") as mock_write,
        ):
            result = cli_runner.invoke(app, ["--reload", "--port-file", str(port_file)])
        assert result.exit_code == 0
        assert "INKFLOW_READY" not in result.output  # 与交付契约互斥
        mock_write.assert_not_called()  # reload 不写端口文件（即使显式 --port-file）
        assert _param(mock_run.call_args, "reload", 2) is True
        assert "🚀" in result.output  # 启动提示照常输出
        assert env_seen["token"]  # _run_server 被调用时 env 已注入
        assert os.environ["INKFLOW_SERVER_TOKEN"] == env_seen["token"]


class TestServeOpenBrowser:
    """--open-browser（保留原测试意图：注册 Timer，不立即打开）."""

    def test_serve_open_browser(self, cli_runner):
        """--open-browser：注册 threading.Timer(1.5, ...) 定时打开文档页，不立即打开."""
        from inkflow.cli.commands.serve import app

        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch("threading.Timer") as mock_timer,
            patch("webbrowser.open") as mock_wb,
        ):
            result = cli_runner.invoke(app, ["--open-browser"])
            assert result.exit_code == 0
            mock_timer.assert_called_once()
            assert mock_timer.call_args.args[0] == 1.5
            # Timer 未触发前不得打开浏览器
            mock_wb.assert_not_called()
            # 触发 Timer 回调 → webbrowser.open 打开 /docs
            # （须在 patch 上下文内触发，否则 webbrowser.open 已还原为真实函数）
            mock_timer.call_args.args[1]()
            mock_wb.assert_called_once_with("http://127.0.0.1:8000/docs")

    def test_serve_open_browser_custom_host_port(self, cli_runner):
        """--open-browser 的 URL 随 --host/--port 变化."""
        from inkflow.cli.commands.serve import app

        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch("threading.Timer") as mock_timer,
            patch("webbrowser.open") as mock_wb,
        ):
            result = cli_runner.invoke(
                app, ["--host", "0.0.0.0", "--port", "9999", "--open-browser"]
            )
            assert result.exit_code == 0
            mock_timer.call_args.args[1]()
            mock_wb.assert_called_once_with("http://0.0.0.0:9999/docs")


# =====================================================================
# 装配缝内部实现（_run_server / _write_port_file）+ serve 尾部生命周期
# =====================================================================


class TestRunServerSeam:
    """_run_server 内部实现：uvicorn 装配参数、--port 0 动态分配、reload 分支。

    测试**不**真实启动 uvicorn：patch uvicorn.Config / uvicorn.Server 与
    serve 模块的 threading.Thread（拦截后台线程创建），断言装配契约。
    """

    def test_non_reload_assembles_uvicorn_and_starts_thread(self):
        """非 reload：Config 装配参数正确 + 后台线程(name/daemon/target=server.run)启动。"""
        import inkflow.cli.commands.serve as serve_mod

        fake_server = MagicMock()
        fake_server.started = True  # 跳过 started 轮询等待
        with (
            patch("uvicorn.Config") as mock_config_cls,
            patch("uvicorn.Server", return_value=fake_server) as mock_server_cls,
            patch(f"{SERVE_MOD}.threading.Thread") as mock_thread_cls,
            patch(f"{SERVE_MOD}._server_thread", None),
            patch(f"{SERVE_MOD}._current_server", None),
        ):
            actual = serve_mod._run_server("127.0.0.1", 8000, False)
            # 模块级运行状态记录（Ctrl+C 优雅关闭用）——须在 patch 生效内断言
            assert serve_mod._current_server is fake_server
            assert serve_mod._server_thread is mock_thread_cls.return_value

        assert actual == 8000
        mock_config_cls.assert_called_once_with(
            "inkflow.api.app:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            log_level="info",
        )
        mock_server_cls.assert_called_once_with(mock_config_cls.return_value)
        # 后台线程：target=server.run、name、daemon=False（保活线程，非守护）
        mock_thread_cls.assert_called_once()
        tcall = mock_thread_cls.call_args
        assert _param(tcall, "target", 0) == fake_server.run
        assert _param(tcall, "name", 1) == "inkflow-uvicorn"
        assert _param(tcall, "daemon", 2) is False
        mock_thread_cls.return_value.start.assert_called_once()

    def test_port_zero_dynamic_allocation(self):
        """--port 0：socket 预绑定取系统分配端口，Config 与实际端口装配。"""
        from inkflow.cli.commands.serve import _run_server

        fake_sock = MagicMock()
        fake_sock.getsockname.return_value = ("127.0.0.1", 43210)
        fake_server = MagicMock()
        fake_server.started = True
        with (
            patch("socket.socket", return_value=fake_sock),
            patch("uvicorn.Config") as mock_config_cls,
            patch("uvicorn.Server", return_value=fake_server),
            patch(f"{SERVE_MOD}.threading.Thread"),
            patch(f"{SERVE_MOD}._server_thread", None),
            patch(f"{SERVE_MOD}._current_server", None),
        ):
            actual = _run_server("0.0.0.0", 0, False)

        assert actual == 43210
        fake_sock.bind.assert_called_once_with(("0.0.0.0", 0))
        fake_sock.close.assert_called_once()
        assert _param(mock_config_cls.call_args, "port", 2) == 43210

    def test_reload_blocks_without_thread(self):
        """reload：直接阻塞调 server.run（supervisor 语义），不创建后台线程。"""
        from inkflow.cli.commands.serve import _run_server

        fake_server = MagicMock()
        with (
            patch("uvicorn.Config") as mock_config_cls,
            patch("uvicorn.Server", return_value=fake_server) as _mock_server_cls,
            patch(f"{SERVE_MOD}.threading.Thread") as mock_thread_cls,
        ):
            actual = _run_server("127.0.0.1", 8000, True)

        assert actual == 8000
        fake_server.run.assert_called_once()
        mock_thread_cls.assert_not_called()
        assert _param(mock_config_cls.call_args, "reload", 3) is True

    def test_run_server_waits_for_started(self):
        """非 reload：server.started 未就绪时轮询等待（while not server.started 循环体）。"""
        import inkflow.cli.commands.serve as serve_mod

        class _FakeServer(MagicMock):
            """started 第一次读 False（进循环）、第二次 True（退出循环）。"""

            _reads = 0

            @property
            def started(self):
                self._reads += 1
                return self._reads > 1

        fake_server = _FakeServer()
        with (
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=fake_server),
            patch(f"{SERVE_MOD}.threading.Thread"),
            patch(f"{SERVE_MOD}._server_thread", None),
            patch(f"{SERVE_MOD}._current_server", None),
            patch("time.sleep") as mock_sleep,
        ):
            actual = serve_mod._run_server("127.0.0.1", 8000, False)

        assert actual == 8000
        assert fake_server._reads == 2  # 循环体至少执行一次后才退出
        mock_sleep.assert_called_once_with(0.02)


class TestWritePortFileSeam:
    """_write_port_file 真实执行：原子写入（tmp + os.replace）。"""

    def test_write_port_file_atomic(self, tmp_path):
        """端口文件真实写入：JSON 内容正确，无 .tmp 残留。"""
        from inkflow.cli.commands.serve import _write_port_file

        target = tmp_path / "serve.json"
        payload = {"port": 8000, "token": "tok", "pid": 123, "version": "0.1.0"}
        _write_port_file(target, payload)

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == payload
        assert not (tmp_path / "serve.json.tmp").exists()

    def test_serve_port_file_real_write(self, cli_runner, tmp_path):
        """serve --port-file：真实调用交付缝写文件，内容与 INKFLOW_READY 行一致。"""
        from inkflow.cli.commands.serve import app

        port_file = tmp_path / "serve.json"
        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result = cli_runner.invoke(app, ["--port-file", str(port_file)])

        assert result.exit_code == 0
        assert port_file.exists()
        assert json.loads(port_file.read_text(encoding="utf-8")) == _parse_ready(
            result.output
        )
        assert not (tmp_path / "serve.json.tmp").exists()


class TestServeShutdown:
    """serve 尾部生命周期：线程 join + Ctrl+C 优雅关闭。"""

    def test_serve_keyboard_interrupt_graceful(self, cli_runner):
        """Ctrl+C：join 抛 KeyboardInterrupt → 置 should_exit → 再 join(timeout=5)。"""
        from inkflow.cli.commands.serve import app

        fake_thread = MagicMock()
        fake_thread.join.side_effect = [KeyboardInterrupt, None]
        fake_server = MagicMock()
        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch(f"{SERVE_MOD}._server_thread", fake_thread),
            patch(f"{SERVE_MOD}._current_server", fake_server),
        ):
            result = cli_runner.invoke(app, [])

        assert result.exit_code == 0  # 内部捕获，不冒泡
        assert fake_thread.join.call_count == 2
        assert fake_thread.join.call_args_list[1].kwargs.get("timeout") == 5
        assert fake_server.should_exit is True  # 通知 uvicorn 优雅退出
        # 交付行在 join 之前已输出
        assert _parse_ready(result.output)["port"] == FAKE_PORT

    def test_serve_keyboard_interrupt_without_current_server(self, cli_runner):
        """Ctrl+C 且 _current_server 为 None：跳过 should_exit，仍 join(timeout=5) 收尾。"""
        from inkflow.cli.commands.serve import app

        fake_thread = MagicMock()
        fake_thread.join.side_effect = [KeyboardInterrupt, None]
        with (
            patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT),
            patch(f"{SERVE_MOD}._server_thread", fake_thread),
            patch(f"{SERVE_MOD}._current_server", None),
        ):
            result = cli_runner.invoke(app, [])

        assert result.exit_code == 0
        assert fake_thread.join.call_count == 2
        assert fake_thread.join.call_args_list[1].kwargs.get("timeout") == 5
        # _current_server 为 None → 不尝试置 should_exit
        assert "INKFLOW_READY" in result.output

    def test_serve_startup_line_shows_host_port(self, cli_runner):
        """启动提示行展示请求的 --host/--port。"""
        from inkflow.cli.commands.serve import app

        with patch(f"{SERVE_MOD}._run_server", return_value=FAKE_PORT):
            result = cli_runner.invoke(app, ["--host", "0.0.0.0", "--port", "9999"])

        assert result.exit_code == 0
        assert "🚀 InkFlow 服务启动于 http://0.0.0.0:9999" in result.output
