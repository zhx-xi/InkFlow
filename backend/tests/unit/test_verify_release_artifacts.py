"""S3f-T2 / contract-s3f-t2 §1 R3：ci_cd/verify_release_artifacts.py 纯函数契约测试。

脚本本体 = 发布验证基建源文件（GREEN 义务，由 Codex 按本文件 docstring 契约实现；
CLI 参数面 / main / 退出码不属本文件锁定范围）。脚本在仓库根 ci_cd/ 下、不属于 backend
包，故经 importlib.util 按路径动态加载（文件缺失 → exec_module 抛 FileNotFoundError）。

RED 预期形态：ci_cd/verify_release_artifacts.py 不存在 → 全部用例 ERROR
（FileNotFoundError），pytest 退出码非 0——本文件不静态 import 脚本，无收集期 ImportError。

GREEN 义务（函数签名 + 语义，以本文件断言为准）：
1. normalize_version(v: str) -> str
   - 去首尾空白；剥前导 'v'/'V'；PEP440 预发布段规范化：'-rc.N' / 'rc.N' → 'rcN'
     （移除连接符与点）——normalize_version('v0.13.0-rc.1') == '0.13.0rc1'；
   - 已 canonical 输入幂等；无预发布段的 'v0.13.0' → '0.13.0'。
2. matches_tag(actual_stdout: str, tag: str) -> bool
   - 版本一致性比对（v 前缀剥离 + rc.1 ↔ rc1 兼容）：stdout 按空白拆 token，任一 token
     经 normalize_version 后 == normalize_version(tag) → True；空 stdout → False。
     'inkflow 0.13.0rc1' 对 tag 'v0.13.0-rc.1' → True。
3. check_cli_zip_structure(namelist: list[str]) -> list[str]
   - 缺失项清单（空列表 = 完整）。期望集（zipfile namelist 正斜杠形态）：
     a. 'inkflow/inkflow.exe' 条目存在；
     b. 'inkflow/_internal/'：存在该目录条目或任一 'inkflow/_internal/...' 条目；
     c. 'inkflow-mcp/inkflow-mcp.exe' 条目存在；
     d. 'skills/' 下至少 1 个子条目（entry.startswith('skills/') 且非裸 'skills/'）。
   - 缺失标签（返回列表元素，规范形式）：'inkflow/inkflow.exe' | 'inkflow/_internal/'
     | 'inkflow-mcp/inkflow-mcp.exe' | 'skills/'。
4. dist_info_count(namelist: list[str]) -> int
   - inkflow 自身 dist-info 份数：统计 'inkflow/_internal/' 下目录名匹配
     'inkflow-*.dist-info' 的条目，按 dist-info 目录名去重计数（同目录 METADATA/RECORD
     多条目计 1）；外来包 dist-info（非 'inkflow-' 前缀）不计入（onedir 可能含依赖
     dist-info，排除防误报）。脚本主体判定：== 1 = copy_metadata 单份合法
     （< 1 = 缺元数据致冻结 exe PackageNotFoundError；> 1 = 重复收集回归）。
5. check_gui_dir_structure(root: Path) -> list[str]
   - GUI 产物目录（win-unpacked / NSIS 安装目录）存在性缺失清单（空列表 = 完整），
     相对标签：'InkFlow.exe'（文件）、'resources/kernel/inkflow.exe'（文件）、
     'resources/kernel/mcp/inkflow-mcp.exe'（文件）、'resources/skills'（目录）。
     asar 内容 / exe --version 冒烟属脚本主体参数面，不在纯函数面。

测试全部用 tmp 构造假 namelist / 假目录骨架（tmp_path），零真实产物依赖。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "verify_release_artifacts.py"

# 合法 CLI zip namelist fixture（镜像 PyInstaller onedir + mcp + skills 组装形态）
VALID_CLI_NAMELIST = [
    "inkflow/",
    "inkflow/inkflow.exe",
    "inkflow/_internal/",
    "inkflow/_internal/python312.dll",
    "inkflow/_internal/inkflow-0.13.0.dist-info/METADATA",
    "inkflow/_internal/inkflow-0.13.0.dist-info/RECORD",
    "inkflow-mcp/",
    "inkflow-mcp/inkflow-mcp.exe",
    "skills/",
    "skills/writing/",
    "skills/writing/SKILL.md",
]


def _load_script():
    """动态加载 ci_cd/verify_release_artifacts.py（RED：文件缺失 → FileNotFoundError）。"""
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_exists_and_exposes_contract_functions() -> None:
    """脚本文件存在 + 五个契约函数可调用（RED：脚本不存在 → 本用例 ERROR）。"""
    module = _load_script()
    for name in (
        "normalize_version",
        "matches_tag",
        "check_cli_zip_structure",
        "dist_info_count",
        "check_gui_dir_structure",
    ):
        assert callable(getattr(module, name)), f"脚本应导出函数 {name}"


def test_normalize_version_contract() -> None:
    """版本规范化：剥 v + PEP440 rc 去点（rc.1 ↔ rc1 兼容比对基础）。"""
    normalize_version = _load_script().normalize_version
    assert normalize_version("v0.13.0-rc.1") == "0.13.0rc1"
    assert normalize_version("0.13.0-rc.1") == "0.13.0rc1"  # 无 v 前缀同规范化
    assert normalize_version("0.13.0rc1") == "0.13.0rc1"  # 幂等（已 canonical）
    assert normalize_version("v0.13.0") == "0.13.0"  # 无预发布段
    assert normalize_version("0.13.1") == "0.13.1"


def test_matches_tag_contract() -> None:
    """stdout 含名/空白 → tokenize 比对；tag/实际版本双向 v+rc 形态兼容。"""
    matches_tag = _load_script().matches_tag
    assert matches_tag("inkflow 0.13.0rc1", "v0.13.0-rc.1") is True  # stdout 带名 + tag 带 v/rc 点
    assert matches_tag("0.13.0rc1", "0.13.0-rc.1") is True
    assert matches_tag("0.13.0", "0.13.0") is True
    assert matches_tag("0.14.0", "v0.13.0") is False  # 版本不符
    assert matches_tag("", "v0.13.0") is False  # 空 stdout


def test_check_cli_zip_structure_complete_namelist() -> None:
    """完整 namelist → 无缺失（空列表）。"""
    check = _load_script().check_cli_zip_structure
    assert check(VALID_CLI_NAMELIST) == []


def test_check_cli_zip_structure_reports_missing_items() -> None:
    """缺 inkflow.exe / 缺 skills 子条目 / 缺 mcp exe → 对应规范标签进缺失清单。"""
    check = _load_script().check_cli_zip_structure
    without_exe = [e for e in VALID_CLI_NAMELIST if e != "inkflow/inkflow.exe"]
    assert sorted(check(without_exe)) == ["inkflow/inkflow.exe"]
    without_skills = [e for e in VALID_CLI_NAMELIST if not e.startswith("skills/")]
    assert sorted(check(without_skills)) == ["skills/"]  # 裸 'skills/' 随过滤剔除 → 空目录不算
    stripped = [
        e
        for e in VALID_CLI_NAMELIST
        if e != "inkflow/inkflow.exe"
        and e != "inkflow-mcp/inkflow-mcp.exe"
        and not e.startswith("skills/")
    ]
    assert sorted(check(stripped)) == [
        "inkflow-mcp/inkflow-mcp.exe",
        "inkflow/inkflow.exe",
        "skills/",
    ]


def test_check_cli_zip_structure_internal_dir_via_entries() -> None:
    """inkflow/_internal/ 无目录条目但有子文件条目 → 仍视为满足（onedir 实体文件存在）。"""
    check = _load_script().check_cli_zip_structure
    no_internal_dir_entry = [e for e in VALID_CLI_NAMELIST if e != "inkflow/_internal/"]
    assert "inkflow/_internal/" not in no_internal_dir_entry
    assert check(no_internal_dir_entry) == []
    only_internal = [
        e
        for e in VALID_CLI_NAMELIST
        if e == "inkflow/_internal/python312.dll"
        or e.startswith("inkflow/_internal/inkflow-0.13.0.dist-info/")
    ]
    assert sorted(check(only_internal)) == [
        "inkflow-mcp/inkflow-mcp.exe",
        "inkflow/inkflow.exe",
        "skills/",
    ]


def test_dist_info_count_contract() -> None:
    """inkflow-*.dist-info 目录数（去重；外来包 dist-info 不计入）。"""
    count = _load_script().dist_info_count
    assert count(VALID_CLI_NAMELIST) == 1  # 单份 = copy_metadata 合法
    assert count([]) == 0
    foreign_only = ["inkflow/_internal/pydantic-2.11.0.dist-info/METADATA"]
    assert count(foreign_only) == 0  # 前缀过滤：外来包不计入（防 onedir 依赖 dist-info 误报）
    duplicated = [*VALID_CLI_NAMELIST, "inkflow/_internal/inkflow-0.13.1.dist-info/METADATA"]
    assert count(duplicated) == 2  # 重复收集回归 → 脚本主体应据此 FAIL


def _build_gui_skeleton(root: Path) -> None:
    """GUI 产物目录骨架（win-unpacked 形态）。"""
    root.mkdir(parents=True)  # 父侧修复（RED helper 缺陷：tmp_path/win-unpacked 未先建）
    (root / "InkFlow.exe").write_bytes(b"")
    (root / "resources" / "kernel").mkdir(parents=True)
    (root / "resources" / "kernel" / "inkflow.exe").write_bytes(b"")
    (root / "resources" / "kernel" / "mcp").mkdir(parents=True)
    (root / "resources" / "kernel" / "mcp" / "inkflow-mcp.exe").write_bytes(b"")
    (root / "resources" / "skills").mkdir(parents=True)


def test_check_gui_dir_structure_complete(tmp_path: Path) -> None:
    """完整 GUI 骨架 → 无缺失。"""
    check = _load_script().check_gui_dir_structure
    root = tmp_path / "win-unpacked"
    _build_gui_skeleton(root)
    assert check(root) == []


def test_check_gui_dir_structure_reports_missing(tmp_path: Path) -> None:
    """缺 mcp exe + 缺 skills 目录 → 对应规范标签进缺失清单。"""
    check = _load_script().check_gui_dir_structure
    root = tmp_path / "win-unpacked"
    _build_gui_skeleton(root)
    (root / "resources" / "kernel" / "mcp" / "inkflow-mcp.exe").unlink()
    (root / "resources" / "skills").rmdir()
    assert sorted(check(root)) == [
        "resources/kernel/mcp/inkflow-mcp.exe",
        "resources/skills",
    ]


def test_check_gui_dir_structure_empty_root(tmp_path: Path) -> None:
    """空目录 → 四项全缺。"""
    check = _load_script().check_gui_dir_structure
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sorted(check(empty)) == [
        "InkFlow.exe",
        "resources/kernel/inkflow.exe",
        "resources/kernel/mcp/inkflow-mcp.exe",
        "resources/skills",
    ]
