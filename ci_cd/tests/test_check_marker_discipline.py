"""契约测试：ci_cd/check_marker_discipline.py 纯函数面 + main 退出码。

护栏职责：文档与代码**不得新增历史标记**（issue 号 / 日期 / 项目版本）。本文件锁定三面：
1. 三类标记能报到（正例）——否则门禁形同虚设；
2. **假阳性集一条都不报**（负例核心）——否则门禁会被噪音淹没而失去意义；
3. 豁免面（路径级 + 行级）生效——否则 CHANGELOG / Nygard 头部会被误伤。

脚本位于仓库根 ci_cd/、不属于 backend 包，故经 importlib.util 按路径动态加载
（与 ci_cd/tests/test_check_doc_pointers.py 同法）。

GREEN 义务（签名 + 语义，以本文件断言为准）：
1. scan_text(text: str, rel: str = "") -> list[tuple[int, str, str]]
   - 返回 [(行号(1 基), kind ∈ {issue,date,version}, 片段)]，按行序；rel 命中豁免路径 → []。
2. is_exempt_path(rel: str) -> bool —— POSIX 风格相对路径；整文件豁免 + 目录跳过。
3. main() 退出码：无命中 0 / 有命中 1 / 参数缺失或非法 2；报告行含 `[check_marker_discipline]`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "check_marker_discipline.py"


def _load_script():
    """动态加载 ci_cd/check_marker_discipline.py（RED：文件缺失 → FileNotFoundError）。"""
    spec = importlib.util.spec_from_file_location("check_marker_discipline", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── 正例：三类标记必须报到 ──────────────────────────────────────────


def test_reports_issue_date_and_version() -> None:
    """正例：三类标记各报 1 条，行号正确。"""
    module = _load_script()
    text = "\n".join(
        [
            "## 概述",
            "该门禁在实现时误报 91/107 假漂移（#1330）。",
            "用户在 2026-09-20 拍板采用方案 B。",
            "该行为自 0.17.0 起生效。",
        ]
    )
    hits = module.scan_text(text, "specs/f19-gui/spec.md")
    kinds = {(lineno, kind) for lineno, kind, _ in hits}
    assert (2, "issue") in kinds, hits
    assert (3, "date") in kinds, hits
    assert (4, "version") in kinds, hits


def test_reports_multiple_hits_per_line_once_each() -> None:
    """每行每类至多报 1 条（防同一行刷屏）。"""
    module = _load_script()
    hits = module.scan_text("见 #1330 与 #1363，以及 2026-09-20、2026-09-21。", "x.md")
    kinds = [k for _, k, _ in hits]
    assert kinds.count("issue") == 1, hits
    assert kinds.count("date") == 1, hits


# ── 负例核心：假阳性集一条都不许报 ──────────────────────────────────


def test_false_positive_family_is_not_reported() -> None:
    """假阳性全家桶（实测去噪清单）：章节号 / 依赖版本 / CSS 色 / IPv4 / URL / ISO 时间戳。"""
    module = _load_script()
    text = "\n".join(
        [
            "见 spec §5.8.3 与 §15.4.1 的约束。",  # 章节号
            "chromadb 1.5.9 + ruff v0.16.1 + loguru 0.7.3",  # 依赖/工具版本
            "- uses: astral-sh/setup-uv@v5",  # action 版本
            'version: "0.11.14"',  # 第三方 action 钉版（YAML 值）
            "background: var(--ink); /* --ink: #2A2A28 */",  # CSS 色值
            "内核监听 127.0.0.1 与 0.0.0.0。",  # IPv4
            "格式见 https://www.conventionalcommits.org/en/v1.0.0/",  # URL
            "created_at: '2026-08-01T10:00:00Z',",  # 测试 mock 时间戳
            # JSON 契约示例（INKFLOW_READY 交付行）
            'INKFLOW_READY {"port": 38291, "token": "aB3x", "pid": 4821, "version": "0.3.0"}',
            # 响应契约示例（/health）
            'GET /health → 200 {"status": "ok", "version": "0.3.0", "mode": "local"}',
            "brain:'<path d=\"M12 5a3 3 0 1 0-5.997.125 4 4\"/>',",  # SVG path
        ]
    )
    hits = module.scan_text(text, "backend/src/inkflow/x.py")
    assert hits == [], f"假阳性被误报: {hits}"


def test_short_number_is_not_reported() -> None:
    """短号（#\\d{1,2}）是混合面（本地枚举 `spec §7 #8`）→ 不检。"""
    module = _load_script()
    text = "见 spec §7 #8、测试契约 #3 与设计假设 #2。"
    assert module.scan_text(text, "specs/f3-writing/spec.md") == []


# ── 豁免面 ─────────────────────────────────────────────────────────


def test_line_exempt_adr_and_spec_headers() -> None:
    """行级豁免：ADR Nygard 头部与 spec 头部元数据行不报。"""
    module = _load_script()
    text = "\n".join(
        [
            "> **日期**: 2026-08-06",
            "> **状态**: ✅ 已接受（v11 修订）",
            "> **依据**: PRD v2.1 §9 + Constitution P1-P6",
            "**Spec 版本**: 1.8（2026-10-08）",
        ]
    )
    assert module.scan_text(text, "adr/test-ci/ADR-027.md") == []


def test_exempt_paths() -> None:
    """路径级豁免：发布账本 / 生成物 / 证据目录。"""
    module = _load_script()
    for rel in (
        "CHANGELOG.md",
        "FEATURES.md",
        "README.md",
        "adr/README.md",
        "ci_cd/openapi_snapshot.json",
        "frontend/packages/renderer/src/api/schema/openapi.d.ts",
        "docs/evidence/contract-929-llm-failfast.md",
        "evidence/shot.png",
        "frontend/node_modules/x/y.md",
    ):
        assert module.is_exempt_path(rel), rel
        assert module.scan_text("（#1330 实测）2026-09-20 0.17.0", rel) == [], rel


def test_non_exempt_path_still_reports() -> None:
    """反例守护：豁免判定不能过宽（普通 spec / 源码要照报）。"""
    module = _load_script()
    for rel in ("specs/f19-gui/spec.md", "backend/src/inkflow/core/config.py", "AGENTS.md"):
        assert not module.is_exempt_path(rel), rel
        assert module.scan_text("（#1330 实测）", rel), rel


def test_exempt_scope_is_single_file_not_directory() -> None:
    """豁免意图守护：检出器**仅**豁免自己那一个测试文件，不是整个 ci_cd/tests/ 或 ci_cd/。"""
    module = _load_script()
    assert module.is_exempt_path("ci_cd/tests/test_check_marker_discipline.py")
    assert not module.is_exempt_path("ci_cd/tests/test_check_doc_pointers.py")
    assert not module.is_exempt_path("ci_cd/check_marker_discipline.py")
    assert not module.is_exempt_path("ci_cd/marker-discipline.md")


# ── --diff：只扫新增行（存量脏文件必须可正常编辑） ────────────────


def test_parse_added_lines_takes_only_additions() -> None:
    """解析 unified diff：只取 `+` 行，行号按 hunk 头递增，删除行与上下文行不取。"""
    module = _load_script()
    diff = "\n".join(
        [
            "diff --git a/x.md b/x.md",
            "index 111..222 100644",
            "--- a/x.md",
            "+++ b/x.md",
            "@@ -10,3 +10,4 @@",
            " 上下文行保持",
            "-被删掉的旧行（#1111 实测）",
            "+新增一行（#2222 实测）",
            "+再增一行 2026-09-20",
            " 尾部上下文",
        ]
    )
    got = module.parse_added_lines(diff)
    # hunk 头 `+10,4`：新文件第 10 行是上下文行，故两条新增行落在 11 / 12
    assert got == {"x.md": [(11, "新增一行（#2222 实测）"), (12, "再增一行 2026-09-20")]}, got


def test_diff_mode_ignores_existing_dirty_lines(tmp_path: Path, monkeypatch, capsys) -> None:
    """核心行为（门禁可用性）：存量已含标记的文件，只改无关行 → --diff 不报。

    否则 W3–W5 期间任何对存量脏文件的编辑都会让门禁恒红。
    """
    import subprocess

    module = _load_script()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    specs = tmp_path / "specs"
    specs.mkdir()
    target = specs / "dirty.md"
    target.write_text("（#1330 实测）存量标记\n", encoding="utf-8")
    git_id = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", *git_id, "commit", "-qm", "init"], cwd=tmp_path, check=True)

    # 只追加一行干净内容（存量标记行不动）
    target.write_text("（#1330 实测）存量标记\n新增的干净说明行。\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_marker_discipline.py", "--diff", "--base", "HEAD"])
    assert module.main() == 0, capsys.readouterr().out

    # 反例：把标记写进**新行** → 必须报
    target.write_text("（#1330 实测）存量标记\n新增一行（#9999 实测）\n", encoding="utf-8")
    assert module.main() == 1
    assert "#9999" in capsys.readouterr().out


# ── main 退出码 ────────────────────────────────────────────────────


def test_main_all_mode_exit_codes(tmp_path: Path, monkeypatch, capsys) -> None:
    """--all：干净 → 0；有标记 → 1；参数形态非法 → 2。"""
    module = _load_script()
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "clean.md").write_text("纯规范，无标记。\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_marker_discipline.py", "--all"])
    assert module.main() == 0
    assert "no history marker" in capsys.readouterr().out

    (tmp_path / "specs" / "dirty.md").write_text("（#1330 实测）\n", encoding="utf-8")
    assert module.main() == 1
    assert "1 hit(s)" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["check_marker_discipline.py"])
    assert module.main() == 2


def test_main_version_external_tool_not_counted_in_all_mode(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """--all 下依赖版本不算命中（端到端复核假阳性抑制不被 main 绕过）。"""
    module = _load_script()
    (tmp_path / "pyproject-ish.toml").write_text('deps = ["chromadb 1.5.9"]\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_marker_discipline.py", "--all"])
    assert module.main() == 0, capsys.readouterr().out
