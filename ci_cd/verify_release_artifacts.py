"""#869 S3f-T2（rc 门禁 P1-P5 脚本化，f19-packaging §4.3 + f33-cli-dist §2.2）：
发布产物结构与版本一致性验证脚本，release.yml 在 tag 触发时调用。

验证面：
1. CLI zip 结构——inkflow/inkflow.exe + inkflow/_internal/ + dist-info 单份
   （copy_metadata 契约）+ inkflow-mcp/inkflow-mcp.exe + skills/ 至少 1 个 skill 目录；
2. 版本一致性——解压 zip 后运行 inkflow/inkflow.exe --version，stdout 与发布 tag
   比对（PEP 440：剥 v 前缀 + rc.1 <-> rc1 兼容，同 release-verification 语义）；
3. 内核 onedir 目录（可选 --kernel-dir，dist/inkflow 形态，与 CLI zip 同源同构）；
4. GUI win-unpacked 目录结构（可选 --gui-dir，electron-builder 默认产出）。

标准库 only（zipfile/pathlib/re/subprocess/tempfile/argparse），Python 3.11+，
`uv run --no-project python` 或任意 3.11+ python 均可运行。纯函数面
（normalize_version / matches_tag / check_cli_zip_structure / dist_info_count /
check_gui_dir_structure）是 backend/tests/unit/test_verify_release_artifacts.py
锁定的契约（RED，禁改）。

CLI：
    python ci_cd/verify_release_artifacts.py --cli-zip <zip> --version <tag>
        [--kernel-dir <onedir>] [--gui-dir <win-unpacked>] [--skip-launch]

stdout 逐项输出 [PASS]/[FAIL] 表；退出码 0 = 全部通过，1 = 存在 FAIL，
2 = 用法错误。--skip-launch：跳过 exe 启动并把该版本项记为 FAIL
（未验证不得 PASS，防 CI 误传该 flag 逃逸）；release 路径不传此 flag。
GUI 验证为纯结构检查，不启动应用。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# PEP 440 预发布段形态：'-rc.1' / 'rc.1' / '-rc1' / 'rc1' 全部收敛为 'rc1'
_PRE_RELEASE_RE = re.compile(r"[-_.]?rc\.?", re.IGNORECASE)


def normalize_version(v: str) -> str:
    """版本规范化：去首尾空白、剥前导 v/V、PEP440 预发布段 '-rc.N'/'rc.N' -> 'rcN'。"""
    text = v.strip()
    if text[:1].lower() == "v":
        text = text[1:]
    return _PRE_RELEASE_RE.sub("rc", text)


def matches_tag(actual_stdout: str, tag: str) -> bool:
    """stdout 按空白拆 token，任一 token 规范化后等于 tag 规范化结果（双向兼容）。"""
    expected = normalize_version(tag)
    return any(normalize_version(token) == expected for token in actual_stdout.split())


def mcp_exe_rel_path() -> str:
    """CLI zip 内 MCP exe 相对路径（#1072 方案 C：结构标签与版本断言同源，防漂移）。"""
    return "inkflow-mcp/inkflow-mcp.exe"


def check_cli_zip_structure(namelist: list[str]) -> list[str]:
    """CLI zip 结构缺失清单：inkflow/inkflow.exe、inkflow/_internal/、MCP exe、skills/。"""
    entries = set(namelist)
    missing: list[str] = []
    if "inkflow/inkflow.exe" not in entries:
        missing.append("inkflow/inkflow.exe")
    if not any(
        e == "inkflow/_internal/" or e.startswith("inkflow/_internal/") for e in entries
    ):
        missing.append("inkflow/_internal/")
    mcp_rel = mcp_exe_rel_path()
    if mcp_rel not in entries:
        missing.append(mcp_rel)
    if not any(e.startswith("skills/") and e != "skills/" for e in entries):
        missing.append("skills/")
    return missing


def dist_info_count(namelist: list[str]) -> int:
    """inkflow/_internal/ 下 inkflow-*.dist-info 目录数（同目录多条目去重计 1）。"""
    dist_infos: set[str] = set()
    prefix = "inkflow/_internal/"
    for entry in namelist:
        if not entry.startswith(prefix):
            continue
        top = entry[len(prefix) :].split("/", 1)[0]
        if top.startswith("inkflow-") and top.endswith(".dist-info"):
            dist_infos.add(top)
    return len(dist_infos)


def check_gui_dir_structure(root: Path) -> list[str]:
    """GUI 产物目录（win-unpacked / NSIS 安装目录）缺失清单，空列表 = 完整。"""
    missing: list[str] = []
    if not (root / "InkFlow.exe").is_file():
        missing.append("InkFlow.exe")
    if not (root / "resources" / "kernel" / "inkflow.exe").is_file():
        missing.append("resources/kernel/inkflow.exe")
    if not (root / "resources" / "kernel" / "mcp" / "inkflow-mcp.exe").is_file():
        missing.append("resources/kernel/mcp/inkflow-mcp.exe")
    if not (root / "resources" / "skills").is_dir():
        missing.append("resources/skills")
    return missing


def _check_kernel_dir_structure(root: Path) -> list[str]:
    """PyInstaller onedir 内核目录（dist/inkflow 形态）结构缺失清单。"""
    missing: list[str] = []
    if not (root / "inkflow.exe").is_file():
        missing.append("inkflow.exe")
    if not (root / "_internal").is_dir():
        missing.append("_internal/")
    return missing


def _kernel_dist_info_count(root: Path) -> int:
    """内核 onedir _internal/ 下的 inkflow-*.dist-info 目录数。"""
    internal = root / "_internal"
    if not internal.is_dir():
        return 0
    return sum(
        1
        for child in internal.iterdir()
        if child.is_dir()
        and child.name.startswith("inkflow-")
        and child.name.endswith(".dist-info")
    )


def _run_exe_version(exe: Path) -> tuple[int | None, str]:
    """运行 <exe> --version 捕获 stdout，返回 (退出码, stdout)；无法启动返回 (None, '')。"""
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return proc.returncode, proc.stdout or ""


def _exe_version_row(exe: Path, tag: str) -> tuple[bool, str]:
    """执行 exe --version 并与 tag 比对，返回 (是否一致, 说明)。"""
    code, stdout = _run_exe_version(exe)
    if code is None:
        return False, f"cannot launch {exe} --version"
    if code != 0:
        return False, f"{exe} --version exited with code {code}"
    if not matches_tag(stdout, tag):
        return False, f"stdout {stdout.strip()!r} does not match tag {tag!r}"
    return True, f"stdout version matches tag {tag}"


def _cli_zip_version_row(zip_path: Path, tag: str) -> tuple[bool, str]:
    """CLI zip 解到临时目录后执行 inkflow/inkflow.exe --version 并比对 tag。"""
    try:
        with tempfile.TemporaryDirectory(prefix="verify-release-") as tmp_dir:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)
            exe = Path(tmp_dir) / "inkflow" / "inkflow.exe"
            if not exe.is_file():
                return False, "inkflow/inkflow.exe missing inside zip"
            return _exe_version_row(exe, tag)
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"zip extraction failed: {exc}"


def _mcp_zip_version_row(zip_path: Path, tag: str) -> tuple[bool, str]:
    """[已废弃 #1078] 保留仅为兼容历史调用点；MCP 入口无 --version 接口，请用 mcp_stdio_row。

    ``inkflow-mcp.exe --version`` 不是产品接口：MCP 入口是纯 stdio JSON-RPC 服务器
    （``mcp/__main__.py`` 仅 ``run()``；``server.py`` ``anyio.run(main)`` → ``stdio_server()``），
    无 CLI 参数解析 → 传 ``--version`` 被忽略，进程进入 stdio 等待、stdin 即关 → exit 0 且
    stdout 为空 → 版本断言恒 FAIL（v0.14.0-rc2 发布阻断，run 34472329168）。
    """
    del zip_path, tag
    return (
        False,
        "deprecated: MCP entry has no --version interface; use mcp_stdio_row()",
    )


#: #1036 契约：MCP 工具面 15→18（与 backend/src/inkflow/mcp/tools/__init__.py
#: MCP_TOOL_REGISTRY 同源）。
MCP_EXPECTED_TOOLS = 18


def mcp_stdio_row(
    mcp_exe: Path, expected: int | None = None, launcher: list[str] | None = None
) -> tuple[bool, str]:
    """MCP 产物健康检查：stdio 握手 initialize → tools/list，断言工具面完整。

    #1078：以 MCP **协议契约**（而非它不具备的 ``--version`` CLI 接口）做门禁，
    可同时捕获「exe 起不来」「协议破」「工具面缺失」三类退化。

    :param mcp_exe: MCP onedir 可执行文件路径（或 launcher 缺省时的直跑目标）
    :param expected: 期望工具数，缺省 ``MCP_EXPECTED_TOOLS``
    :param launcher: 显式启动命令（测试注入 python 桩用）；缺省 ``[exe]``
    :return: ``(是否通过, 说明)``；任何异常路径均返回 ``(False, 说明)`` 不抛出
    """
    want = MCP_EXPECTED_TOOLS if expected is None else expected
    target = Path(mcp_exe)
    if launcher is None and not target.is_file():
        return False, f"MCP exe not found: {target}"

    frames = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "verify-release-artifacts", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    cmd = [str(target)] if launcher is None else list(launcher)
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(target.parent) if launcher is None else None,
        )
        assert proc.stdin is not None and proc.stdout is not None
        # 逐帧写入；initialize 响应与 tools/list 响应各占一行（协议：帧独占 stdout）
        for frame in frames:
            proc.stdin.write(json.dumps(frame) + "\n")
            proc.stdin.flush()

        init_raw = proc.stdout.readline()
        if not init_raw.strip():
            return False, "no initialize response (stdio handshake failed)"
        init = json.loads(init_raw)
        if "result" not in init:
            return False, f"initialize error: {init.get('error')}"

        list_raw = proc.stdout.readline()
        if not list_raw.strip():
            return False, "no tools/list response"
        listed = json.loads(list_raw)
        tools = listed.get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools if isinstance(t, dict)]
        if len(names) < want:
            return False, f"tools/list returned {len(names)} (< {want}): {names[:6]}"
        return (
            True,
            f"stdio handshake OK, tools={len(names)} names={sorted(names)[:3]}...",
        )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        return False, f"stdio handshake failed: {type(exc).__name__}: {exc}"
    finally:
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _mcp_zip_stdio_row(zip_path: Path) -> tuple[bool, str]:
    """CLI zip 解到临时目录 → 对 inkflow-mcp/inkflow-mcp.exe 做 stdio 握手（#1078）。"""
    rel = mcp_exe_rel_path()
    try:
        with tempfile.TemporaryDirectory(prefix="verify-release-mcp-") as tmp_dir:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)
            exe = Path(tmp_dir) / Path(rel)
            if not exe.is_file():
                return False, f"{rel} missing inside zip"
            return mcp_stdio_row(exe)
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"zip extraction failed: {exc}"


def _report(rows: list[tuple[str, bool, str]]) -> int:
    """逐项打印 [PASS]/[FAIL] 表并返回退出码（0 = 全部通过，1 = 存在 FAIL）。"""
    failed = 0
    for label, ok, detail in rows:
        status = "PASS" if ok else "FAIL"
        suffix = f": {detail}" if detail else ""
        print(f"[{status}] {label}{suffix}")
        if not ok:
            failed += 1
    if failed:
        print(f"VERDICT: FAIL ({failed} item(s) failed)")
        return 1
    print("VERDICT: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：逐项验证并返回退出码 0/1（用法错误由 argparse 以 2 退出）。"""
    parser = argparse.ArgumentParser(
        prog="verify_release_artifacts",
        description=(
            "Verify release artifacts (CLI zip / kernel onedir / GUI win-unpacked) "
            "structure and version consistency. #869 S3f-T2 rc gate."
        ),
    )
    parser.add_argument(
        "--cli-zip",
        type=Path,
        metavar="ZIP",
        help="CLI release zip (PyInstaller onedir + inkflow-mcp + skills)",
    )
    parser.add_argument(
        "--version",
        dest="tag",
        metavar="TAG",
        help="release tag/version, e.g. v0.13.0-rc.1",
    )
    parser.add_argument(
        "--kernel-dir",
        type=Path,
        metavar="DIR",
        help="PyInstaller onedir kernel dir, e.g. backend/dist/inkflow",
    )
    parser.add_argument(
        "--gui-dir",
        type=Path,
        metavar="DIR",
        help="GUI artifact dir, e.g. packages/electron/dist/win-unpacked",
    )
    parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="skip exe launch; the version item then FAILs as unverified",
    )
    args = parser.parse_args(argv)

    if args.cli_zip is None and args.kernel_dir is None and args.gui_dir is None:
        parser.error("one of --cli-zip / --kernel-dir / --gui-dir is required")
    if (args.cli_zip is not None or args.kernel_dir is not None) and args.tag is None:
        parser.error("--cli-zip / --kernel-dir require --version TAG")

    rows: list[tuple[str, bool, str]] = []

    if args.cli_zip is not None:
        label_structure = (
            "CLI zip structure (inkflow/inkflow.exe, _internal, inkflow-mcp, skills)"
        )
        label_dist = "CLI zip single inkflow-*.dist-info"
        label_version = "CLI zip version == tag (inkflow.exe --version)"
        label_mcp_version = "CLI zip MCP stdio handshake (tools/list)"
        try:
            with zipfile.ZipFile(args.cli_zip) as zf:
                namelist = zf.namelist()
        except (OSError, zipfile.BadZipFile) as exc:
            rows.append((label_structure, False, f"cannot open {args.cli_zip}: {exc}"))
            rows.append((label_dist, False, "zip unreadable"))
            rows.append((label_version, False, "zip unreadable"))
            rows.append((label_mcp_version, False, "zip unreadable"))
        else:
            missing = check_cli_zip_structure(namelist)
            detail = "complete" if not missing else "missing: " + ", ".join(missing)
            rows.append((label_structure, not missing, detail))
            count = dist_info_count(namelist)
            rows.append((label_dist, count == 1, f"count = {count}"))
            if args.skip_launch:
                rows.append((label_version, False, "--skip-launch: unverified"))
                rows.append((label_mcp_version, False, "--skip-launch: unverified"))
            else:
                ok, detail = _cli_zip_version_row(args.cli_zip, args.tag)
                rows.append((label_version, ok, detail))
                ok_mcp, detail_mcp = _mcp_zip_stdio_row(args.cli_zip)
                rows.append((label_mcp_version, ok_mcp, detail_mcp))

    if args.kernel_dir is not None:
        label_structure = "Kernel dir structure (inkflow.exe, _internal)"
        label_dist = "Kernel dir single inkflow-*.dist-info"
        label_version = "Kernel dir version == tag (inkflow.exe --version)"
        root = args.kernel_dir
        if not root.is_dir():
            rows.append((label_structure, False, f"directory not found: {root}"))
            rows.append((label_dist, False, "directory not found"))
            rows.append((label_version, False, "directory not found"))
        else:
            missing = _check_kernel_dir_structure(root)
            detail = "complete" if not missing else "missing: " + ", ".join(missing)
            rows.append((label_structure, not missing, detail))
            count = _kernel_dist_info_count(root)
            rows.append((label_dist, count == 1, f"count = {count}"))
            if args.skip_launch:
                rows.append((label_version, False, "--skip-launch: unverified"))
            else:
                ok, detail = _exe_version_row(root / "inkflow.exe", args.tag)
                rows.append((label_version, ok, detail))

    if args.gui_dir is not None:
        label = "GUI dir structure (InkFlow.exe, resources/kernel, resources/skills)"
        if not args.gui_dir.is_dir():
            rows.append((label, False, f"directory not found: {args.gui_dir}"))
        else:
            missing = check_gui_dir_structure(args.gui_dir)
            detail = "complete" if not missing else "missing: " + ", ".join(missing)
            rows.append((label, not missing, detail))

    return _report(rows)


if __name__ == "__main__":
    sys.exit(main())
