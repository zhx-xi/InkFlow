"""测试归属映射 v2 — 用 src 目录结构作为 ground truth。

遍历 tests/unit/test_*.py，正则扫 from/import inkflow.X.Y 和 patch("inkflow.X.Y")，
取主目标（排除 domain.models 造数据引用），再用 src 目录结构验证归属。
输出 domain/services/ 和 api/routers/ 两桶映射表（本批范围）。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
UNIT_DIR = BACKEND / "tests" / "unit"
SRC_DIR = BACKEND / "src" / "inkflow"

# 域服务模块集合（domain/services/*.py 去掉 .py）
DS_MODULES = {
    p.stem for p in (SRC_DIR / "domain" / "services").glob("*.py") if not p.name.startswith("__")
}
# API 路由模块集合（api/routers/*.py 去掉 .py）
AR_MODULES = {
    p.stem for p in (SRC_DIR / "api" / "routers").glob("*.py") if not p.name.startswith("__")
}

IMPORT_RE = re.compile(r"from\s+inkflow\.(\w+)\.(\w+)")
PATCH_RE = re.compile(r'patch\(\s*["\']inkflow\.(\w+)\.(\w+)')

# 测试变体后缀（剥离），保留 _service/_repo/_models
VARIANT_SUFFIXES = [
    "_api",
    "_coverage",
    "_gaps",
    "_errors",
    "_p378",
    "_stage1",
    "_stage2",
    "_stage3",
    "_stage4",
    "_stage5",
    "_v1",
    "_v2",
    "_v3",
    "_v4",
    "_v5",
    "_background",
    "_start_mode",
    "_overflow_guards",
    "_user",
    "_m2_summarize",
    "_wiring",
    "_prune",
    "_update",
    "_run",
    "_list",
]


def strip_variant_suffix(stem: str) -> str:
    """剥离测试变体后缀，保留 _service/_repo/_models 层词。"""
    for suffix in sorted(VARIANT_SUFFIXES, key=len, reverse=True):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def classify_file(filepath: Path) -> str | None:
    """返回目标桶 ('domain/services' 或 'api/routers') 或 None。"""
    text = filepath.read_text(encoding="utf-8", errors="replace")
    imports = IMPORT_RE.findall(text)
    patches = PATCH_RE.findall(text)
    all_refs = imports + patches

    # 统计非 domain.models 的引用
    targets: Counter[str] = Counter()
    for pkg, mod in all_refs:
        if pkg == "domain" and mod == "models":
            continue  # 排除造数据引用
        targets[f"{pkg}.{mod}"] += 1

    # 主目标判定
    if targets:
        main_target = targets.most_common(1)[0][0]
        pkg, mod = main_target.split(".", 1)

        # 直接匹配
        if pkg == "domain" and mod == "services":
            return "domain/services"
        if pkg == "api" and mod in ("routers", "deps", "app", "deps_kg_extract"):
            return "api/routers"

    # fallback：用文件名核心词在 src 目录结构中匹配
    stem = filepath.stem  # test_book_service
    core = strip_variant_suffix(stem.replace("test_", "", 1))

    # 检查 core 是否对应 domain/services/ 下的模块
    # core 可能是 "book_service" → 在 DS_MODULES 中找 "book_service"
    # 也可能是 "chunking" → 匹配 "_chunking"（私有模块）
    if core in DS_MODULES:
        return "domain/services"
    # 私有模块：文件名 test_chunking → core "chunking" → src "_chunking"
    if f"_{core}" in DS_MODULES:
        return "domain/services"

    # 检查 core 是否对应 api/routers/ 下的模块
    if core in AR_MODULES:
        return "api/routers"

    # 文件名含 _api 后缀（变体已剥离后仍含 _api）→ 检查是否测试 API 层
    if "_api" in stem:
        # 确认有 api.routers 或 api. 的 patch/import
        if any(pkg == "api" for pkg, _ in all_refs):
            return "api/routers"

    # deps_assembly 类文件 → api 层装配测试
    if "deps" in core and (
        "assembly" in core or core.startswith("book_") or core.startswith("planner_")
    ):
        if any(pkg == "api" for pkg, _ in all_refs):
            return "api/routers"

    return None


def main() -> None:
    test_files = sorted(UNIT_DIR.glob("test_*.py"))
    mapping: dict[str, str | None] = {}
    for tf in test_files:
        bucket = classify_file(tf)
        mapping[tf.name] = bucket

    # 输出本批范围
    print("=" * 60)
    print("domain/services 桶:")
    print("=" * 60)
    ds_files = [f for f, b in mapping.items() if b == "domain/services"]
    for f in sorted(ds_files):
        print(f"  {f}")
    print(f"\n  小计: {len(ds_files)} 文件\n")

    print("=" * 60)
    print("api/routers 桶:")
    print("=" * 60)
    ar_files = [f for f, b in mapping.items() if b == "api/routers"]
    for f in sorted(ar_files):
        print(f"  {f}")
    print(f"\n  小计: {len(ar_files)} 文件\n")

    skipped = [f for f, b in mapping.items() if b is None]
    print("=" * 60)
    print(f"跳过（后续批次）: {len(skipped)} 文件")
    print("=" * 60)

    print(f"\n总计: {len(mapping)} 文件")
    print(f"  domain/services: {len(ds_files)}")
    print(f"  api/routers: {len(ar_files)}")
    print(f"  跳过: {len(skipped)}")

    # 输出 JSON 供后续脚本消费
    import json

    output = {f: b for f, b in mapping.items() if b is not None}
    out_path = UNIT_DIR.parent / "unit_split_mapping.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n映射 JSON 已写入: {out_path}")


if __name__ == "__main__":
    main()
