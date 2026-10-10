"""#342 随包分发静态契约测试（三通道②落地，2026-08-14）。

背景：#70 三通道②（随安装包内置）漂移——0.8.0-rc2 验证便携版 resources/ 只有
kernel + app.asar，无 skills 目录；CLI zip 也无 skills。D3 拍板 B：打包 + install
内置源导入。

本文件把「打包配置必须包含 skills」固化为静态契约（对齐 test_pyinstaller_spec.py
模式：打包收集配置漂移 → CI 红）：
- electron-builder.yml extraResources 必须含 skills（GUI 便携/安装版）
- release.yml CLI zip 打包步骤必须含 skills（CLI 通道）
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/tests/unit → 仓库根
ELECTRON_BUILDER = REPO_ROOT / "frontend" / "packages" / "electron" / "electron-builder.yml"
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
SKILLS_DIR = REPO_ROOT / "skills" / "inkflow"


def test_electron_builder_extra_resources_include_skills():
    """#342: electron-builder extraResources 必须含 skills（随包分发 GUI 侧）。"""
    assert ELECTRON_BUILDER.exists(), f"electron-builder.yml 不存在: {ELECTRON_BUILDER}"
    src = ELECTRON_BUILDER.read_text(encoding="utf-8")
    assert "skills" in src, "extraResources 缺少 skills（#342：GUI 随包分发）"


def test_release_yml_cli_zip_includes_skills():
    """#342: release.yml CLI zip 打包必须含 skills（CLI 通道随包分发）。"""
    assert RELEASE_YML.exists(), f"release.yml 不存在: {RELEASE_YML}"
    src = RELEASE_YML.read_text(encoding="utf-8")
    assert "skills" in src, "release.yml 缺少 skills（#342：CLI zip 随包分发）"


def test_skills_package_exists():
    """#342 前提：仓库官方 skills 包存在（随包源 = 单一真相）。"""
    assert SKILLS_DIR.is_dir(), f"skills/inkflow 不存在: {SKILLS_DIR}"
    assert (SKILLS_DIR / "SKILL.md").is_file(), "skills/inkflow/SKILL.md 缺失"


def test_kernel_md_documents_debug_no_browser_escape_hatch():
    """#1572：外部 skill kernel.md 必须记载 F51 v1.1 逃生门 INKFLOW_DEBUG_NO_BROWSER（#949）。

    内置 skill（`backend/src/inkflow/i18n/skills/{zh,en}/system.md`）已记载该键；外部
    agent skill（`skills/inkflow/`）此前只写「`serve --debug` … 自动打开 `/docs`」，
    零处提及逃生门 → 只读外部 skill 的 agent 不知道如何消除 debug 态自动弹浏览器，
    e2e / 无头 / 批量验证被窗口打断（rc 验证判据「debug 态不弹浏览器」也无知识锚点）。
    本断言把「外部 skill 记载该键 + `--open-browser` 不受影响」固化为静态契约，
    文档再漂移即 CI 红（外部 skill 与内置 skill 是 #563 的两个实体，须各自留痕）。
    """
    kernel = (SKILLS_DIR / "references" / "kernel.md").read_text(encoding="utf-8")
    assert "INKFLOW_DEBUG_NO_BROWSER" in kernel, (
        "kernel.md 未记载 INKFLOW_DEBUG_NO_BROWSER 逃生门（#1572）"
    )
    # 语义边界也须在册：`--open-browser` 显式路径不受该逃生门影响
    assert "--open-browser" in kernel, "kernel.md 未说明 --open-browser 显式路径不受影响（#1572）"
