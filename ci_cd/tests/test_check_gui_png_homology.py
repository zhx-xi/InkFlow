"""契约测试（#1330 层②）：ci_cd/check_gui_png_homology.py 判定面 + 退出码 + 无副作用。

护栏职责：校验 ``design/GUI/<page>/*.png`` 是否仍等于「用当前 HTML 重出的图」。
根因（#1363/#1369 实测）：原型 HTML 改了但同 PR 只重出「新增的状态图」，旧状态图被落下
（8.9%–11.3% 像素差）→ 图与 HTML 不同源，评审/GUI 复验依据失真。
本题不做「原型 ↔ 实现」比对（那是层③，成本高且已转出）。

与层① 的分工：``ci_cd/check_gui_spec_sync.py`` 只查「目录 ↔ 页规格」的存在性对应与头部指针，
**不查任何 PNG 内容**；本门禁只查 PNG 内容同源性，不碰目录/规格对应。

契约（函数签名 + 语义，以本文件断言为准）：

1. 阈值常量（沿用 #1363/#1369 实测量级）
   - ``NOISE_MAX_MAXDIFF == 3``  最大通道差 ≤ 3 = 合成取整/抗锯齿，非漂移
     （#1369 实测：真漂移 maxdiff 34–215，噪声 maxdiff 1）
   - ``NOISE_MAX_PIXELS == 20``  差异像素 ≤ 20 = 光标闪烁级，非漂移
     （#1363 实测 10–20 px）
   - ``IDENTICAL == "identical"`` / ``NOISE == "noise"`` / ``DRIFT == "drift"``

2. ``classify_diff(result: DiffResult) -> str``
   - 尺寸不同 → DRIFT（重出出了别的视口，是真实差异）
   - ``pixels == 0`` → IDENTICAL
   - ``max_channel_diff <= NOISE_MAX_MAXDIFF`` → NOISE
   - ``pixels <= NOISE_MAX_PIXELS`` → NOISE
   - 其余 → DRIFT
   - ⚠️ 两个阈值都是**绝对**量（像素数 / 通道差），**不得**再叠加比例/百分比守卫 ——
     真实截图 ≈1280×800（≈10⁶ px），#1363/#1369 的噪声量级（10–20 px、maxdiff ≤1）
     本身就是在这类图上实测出来的绝对值；加比例守卫会静默改变小图判定。

3. ``read_png_pixels(path) -> (width, height, rgb_bytes)``
   - **RGB(color=2) 与 RGBA(color=6) 必须统一剥到 3 通道**再比（#1363 坑：新旧图色彩类型
     不同，硬断言 RGBA 直接 AssertionError）
   - 其他 color type / 位深 / 隔行 → 抛 ``PngFormatError``

4. ``diff_png(baseline: Path, candidate: Path) -> DiffResult``
   - ``pixels`` / ``max_channel_diff`` / ``bbox``（(xmin, ymin, xmax, ymax)，无差异时 None）
     / ``total_pixels`` / ``same_size``

5. ``load_exempt(path: Path) -> dict[str, str]``（PNG 相对路径 → 豁免理由）
   - 结构非法（非 dict / 缺 "exempt" / "exempt" 非列表 / 条目缺 png 或 reason）→ ``ValueError``

6. ``find_coverage_gaps(*, disk, produced, exempt) -> list[str]``
   - ``unregistered: <png>``  盘上有、无脚本产出、也未登记豁免 → 缺口（**禁止静默跳过**）
   - ``stale-exempt: <png>``  登记了豁免但盘上已无该图 → 缺口（登记表腐烂）
   - 返回按字符串排序；无缺口 → []

7. ``check_homology(repo_root, *, runner=None) -> HomologyReport``
   - ``runner(script: Path, repo_root: Path) -> int``：执行一个 shot 脚本并返回退出码；
     默认实现走 ``node``；测试注入假 runner 以脱离 node / playwright。
   - **产出集判据 = 运行前后 (mtime_ns, size) 变化或文件新增**：脚本把图**原样重出**
     （逐字节相同）也必须算「有脚本产出」——否则会误判成「无脚本覆盖」→ 假 FAIL。
   - ⚠️ **跑脚本前必须把每张 PNG 的 mtime 归到「远古基准」**（`os.utime(..., ns=(0, 0))` 之类）：
     Windows/NTFS 的文件时间粒度约 15.6ms，**同一时钟刻度内的原样重出 mtime 不变**
     （探针实证：连续两次 `write_bytes` 同值 mtime）→ 纯 mtime 判据会把「脚本原样重出」
     误判成 `unregistered`（假红）。归一化后任何真实写入都远晚于基准，判据确定可靠；
     原始 mtime 与字节一并在 `finally` 还原。
   - ``report.ok`` 仅在「无漂移 且 无缺口 且 无脚本失败」时为 True。
   - **无副作用**：跑完必须把每张 PNG 还原为运行前字节（工作树不得被门禁改脏）。
     CI 里无害；本地/pre-push 里这是「可反复跑」的前提。

8. ``main()`` 退出码（读 ``sys.argv``，与 ci_cd 既有门禁同形）
   - ``0`` 通过；``1`` 有漂移 / 覆盖缺口 / 脚本失败；``2`` 缺参数或配置错（exempt 文件缺失/非法）
   - 报告行须含：页名、状态名、``px=``、``maxdiff=``、``bbox=``（验收要求的可归因信息）
   - 非 UTF-8 stdout（Windows runner cp1252）下不得抛 UnicodeEncodeError

测试全部用 tmp 构造假仓库（与 test_check_gui_spec_sync.py 同法），零真实仓库依赖；
真实仓库口径由验收命令 ``python ci_cd/check_gui_png_homology.py .`` 在主仓根实测。
"""

from __future__ import annotations

import importlib.util
import io
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "check_gui_png_homology.py"

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _load_script():
    """动态加载 ci_cd/check_gui_png_homology.py（RED：文件缺失 → FileNotFoundError）。

    必须先注册进 ``sys.modules`` 再 ``exec_module``：本仓 ci_cd 门禁脚本一律按文件路径
    动态加载，而 Python 3.13 的 ``@dataclass`` 解析 PEP 563 字符串注解时会回查
    ``sys.modules[cls.__module__]``——未注册即 ``AttributeError: 'NoneType' object has
    no attribute '__dict__'``（探针实证）。注册后 dataclass 正常构建，实现端不需要
    任何注解求值 workaround。
    """
    spec = importlib.util.spec_from_file_location("check_gui_png_homology", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_gui_png_homology"] = module
    spec.loader.exec_module(module)
    return module


# ─────────────────────────── 合成 PNG（测试夹具，零依赖） ───────────────────────────


def _chunk(tag: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(tag + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)


def _png_bytes(
    width: int,
    height: int,
    default: tuple[int, ...],
    *,
    color: int = 2,
    overrides: dict[tuple[int, int], tuple[int, ...]] | None = None,
    filter_type: int = 0,
) -> bytes:
    """构造真实（可被 zlib/PngFilter 反解）的 PNG 字节。

    color=2 → RGB(3 通道)；color=6 → RGBA(4 通道)。filter_type 仅支持 0（None），
    测试不需要别的滤波器（生产图确有 Paeth/Up/Sub，由真实仓库验收命令覆盖）。
    """
    bpp = 3 if color == 2 else 4
    assert len(tuple(default)) == bpp
    ov = overrides or {}
    rows = bytearray()
    for y in range(height):
        rows.append(filter_type)
        for x in range(width):
            px = tuple(ov.get((x, y), default))
            assert len(px) == bpp, f"override {px} 通道数须等于 {bpp}"
            rows += bytes(px)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return (
        _PNG_SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows)))
        + _chunk(b"IEND", b"")
    )


def _png_file(path: Path, *args: Any, **kwargs: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes(*args, **kwargs))
    return path


# ─────────────────────────── 假仓库 ───────────────────────────


def _make_repo(
    root: Path,
    *,
    scripts: dict[str, list[str]],
    pngs: dict[str, tuple[int, int, tuple[int, ...]]],
    exempt: list[dict[str, str]] | None = None,
) -> Path:
    """构造假仓库。

    scripts: {脚本名: [PNG 相对 design/GUI 路径, ...]}（写成合法 shot-*.cjs 占位文件）
    pngs:    {PNG 相对路径: (w, h, RGB 填充色)}
    exempt:  ci_cd/gui_png_homology_exempt.json 的 "exempt" 列表内容
    """
    gui = root / "design" / "GUI"
    for rel, (w, h, fill) in pngs.items():
        page = rel.split("/", 1)[0]
        _png_file(gui / rel, w, h, fill)
        (gui / page / f"{page}.html").write_text("<html></html>", encoding="utf-8")
    tools = gui / "_tools"
    tools.mkdir(parents=True, exist_ok=True)
    for name in scripts:
        (tools / name).write_text("// stub\n", encoding="utf-8")
    ci = root / "ci_cd"
    ci.mkdir(parents=True, exist_ok=True)
    import json

    (ci / "gui_png_homology_exempt.json").write_text(
        json.dumps({"note": "test", "exempt": exempt or []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


def _fake_runner(writes: dict[str, dict[str, bytes]]):
    """造一个假 runner：脚本名 → {PNG 相对路径: 要写入的字节}。返回 (runner, calls)。"""
    calls: list[str] = []

    def runner(script: Path, repo_root: Path) -> int:
        calls.append(script.name)
        for rel, data in writes.get(script.name, {}).items():
            target = repo_root / "design" / "GUI" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return 0

    return runner, calls


def _cp1252_stdout(monkeypatch) -> io.TextIOWrapper:
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", wrapper)
    return wrapper


# ─────────────────────────── 1/2. 常量与 classify_diff ───────────────────────────


def test_script_exposes_contract_surface() -> None:
    """脚本存在且导出契约符号（RED：脚本不存在 → 本用例 ERROR）。"""
    module = _load_script()
    for name in (
        "classify_diff",
        "diff_png",
        "read_png_pixels",
        "load_exempt",
        "find_coverage_gaps",
        "check_homology",
        "main",
        "DiffResult",
        "HomologyReport",
    ):
        assert hasattr(module, name), f"脚本应导出 {name}"
    assert module.NOISE_MAX_MAXDIFF == 3
    assert module.NOISE_MAX_PIXELS == 20
    assert (module.IDENTICAL, module.NOISE, module.DRIFT) == ("identical", "noise", "drift")


def _diff(module, **kw) -> Any:
    base = {
        "pixels": 0,
        "max_channel_diff": 0,
        "bbox": None,
        "total_pixels": 10_000,
        "same_size": True,
    }
    base.update(kw)
    return module.DiffResult(**base)


def test_classify_identical() -> None:
    module = _load_script()
    assert module.classify_diff(_diff(module)) == module.IDENTICAL


def test_classify_noise_by_maxdiff_even_when_many_pixels() -> None:
    """#1369 灰区：数千 px 但 maxdiff=1（确定性合成取整）→ NOISE，不误报。"""
    module = _load_script()
    r = _diff(module, pixels=21883, max_channel_diff=1, bbox=(8, 11, 1256, 792))
    assert module.classify_diff(r) == module.NOISE


def test_classify_noise_by_pixel_count_even_with_contrast() -> None:
    """光标闪烁级：13 px 但通道差可达数百 → 仍判 NOISE（#1363 实测量级）。"""
    module = _load_script()
    r = _diff(module, pixels=13, max_channel_diff=255, bbox=(888, 243, 977, 245))
    assert module.classify_diff(r) == module.NOISE


def test_classify_drift_on_real_drift_magnitude() -> None:
    """#1369 真漂移实测量级（6408 px / maxdiff 209）→ DRIFT。"""
    module = _load_script()
    r = _diff(module, pixels=6408, max_channel_diff=209, bbox=(379, 362, 1208, 395))
    assert module.classify_diff(r) == module.DRIFT


def test_classify_size_mismatch_is_drift() -> None:
    """视口/尺寸不同（重出用了别的 viewport）→ DRIFT，不因「无法逐像素」而放过。"""
    module = _load_script()
    r = _diff(module, pixels=0, max_channel_diff=0, same_size=False, total_pixels=100)
    assert module.classify_diff(r) == module.DRIFT


# ─────────────────────────── 3/4. 像素读取与比对 ───────────────────────────


def test_read_png_pixels_normalizes_rgba_to_rgb(tmp_path: Path) -> None:
    """RGB 与 RGBA 同图 → 像素缓冲逐字节相同（#1363 色彩类型坑）。"""
    module = _load_script()
    rgb = _png_file(tmp_path / "a.png", 4, 3, (10, 20, 30), color=2)
    rgba = _png_file(tmp_path / "b.png", 4, 3, (10, 20, 30, 255), color=6)
    w1, h1, p1 = module.read_png_pixels(rgb)
    w2, h2, p2 = module.read_png_pixels(rgba)
    assert (w1, h1) == (4, 3) == (w2, h2)
    assert p1 == p2
    assert len(p1) == 4 * 3 * 3


def test_read_png_pixels_rejects_unknown_format(tmp_path: Path) -> None:
    module = _load_script()
    bad = tmp_path / "p.png"
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0)  # color=0 灰度：不支持
    bad.write_bytes(_PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b""))
    with pytest.raises(module.PngFormatError):
        module.read_png_pixels(bad)


def test_diff_png_identical_across_color_types(tmp_path: Path) -> None:
    module = _load_script()
    a = _png_file(tmp_path / "a.png", 6, 4, (1, 2, 3), color=2)
    b = _png_file(tmp_path / "b.png", 6, 4, (1, 2, 3, 255), color=6)
    r = module.diff_png(a, b)
    assert module.classify_diff(r) == module.IDENTICAL
    assert r.pixels == 0 and r.max_channel_diff == 0 and r.bbox is None
    assert r.same_size is True


def test_diff_png_counts_pixels_maxdiff_and_bbox(tmp_path: Path) -> None:
    module = _load_script()
    a = _png_file(tmp_path / "a.png", 8, 8, (0, 0, 0))
    # 25 px（5×5 块）> NOISE_MAX_PIXELS(20)：明确越过噪声地板，不与「光标闪烁级」混淆
    block = {(x, y): (255, 0, 0) for x in range(5) for y in range(5)}
    b = _png_file(tmp_path / "b.png", 8, 8, (0, 0, 0), overrides=block)
    r = module.diff_png(a, b)
    assert r.pixels == 25
    assert r.max_channel_diff == 255
    assert r.bbox == (0, 0, 4, 4)
    assert r.total_pixels == 64
    assert module.classify_diff(r) == module.DRIFT


def test_diff_png_detects_size_mismatch(tmp_path: Path) -> None:
    module = _load_script()
    a = _png_file(tmp_path / "a.png", 8, 8, (0, 0, 0))
    b = _png_file(tmp_path / "b.png", 8, 6, (0, 0, 0))
    r = module.diff_png(a, b)
    assert r.same_size is False
    assert module.classify_diff(r) == module.DRIFT


# ─────────────────────────── 5/6. 豁免登记与覆盖缺口 ───────────────────────────


def _write_exempt(path: Path, payload: object) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_exempt_ok(tmp_path: Path) -> None:
    module = _load_script()
    p = _write_exempt(
        tmp_path / "e.json",
        {"note": "n", "exempt": [{"png": "writing/x.png", "reason": "历史手工出图"}]},
    )
    assert module.load_exempt(p) == {"writing/x.png": "历史手工出图"}


def test_load_exempt_empty_list_is_empty_dict(tmp_path: Path) -> None:
    module = _load_script()
    p = _write_exempt(tmp_path / "e.json", {"exempt": []})
    assert module.load_exempt(p) == {}


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "a", "dict"],
        {"note": "缺 exempt"},
        {"exempt": "not-a-list"},
        {"exempt": [{"reason": "缺 png"}]},
        {"exempt": [{"png": "a.png"}]},
    ],
)
def test_load_exempt_rejects_malformed(tmp_path: Path, payload: object) -> None:
    module = _load_script()
    p = _write_exempt(tmp_path / "e.json", payload)
    with pytest.raises(ValueError):
        module.load_exempt(p)


def test_find_coverage_gaps_clean() -> None:
    module = _load_script()
    gaps = module.find_coverage_gaps(disk={"a/a-main.png"}, produced={"a/a-main.png"}, exempt={})
    assert gaps == []


def test_find_coverage_gaps_unregistered_png_is_a_gap() -> None:
    """核心（防静默跳过）：盘上有图、没有脚本产出、也未登记 → 必须报缺口。"""
    module = _load_script()
    gaps = module.find_coverage_gaps(
        disk={"a/a-main.png", "b/b-main.png"},
        produced={"a/a-main.png"},
        exempt={},
    )
    assert gaps == ["unregistered: b/b-main.png"]


def test_find_coverage_gaps_exempt_is_honored() -> None:
    module = _load_script()
    gaps = module.find_coverage_gaps(
        disk={"a/a-main.png", "b/b-main.png"},
        produced={"a/a-main.png"},
        exempt={"b/b-main.png": "无出图脚本（历史手工资产）"},
    )
    assert gaps == []


def test_find_coverage_gaps_stale_exempt_is_a_gap() -> None:
    """登记表腐烂：豁免项指向的图已不存在 → 必须报缺口（否则清单会静默失效）。"""
    module = _load_script()
    gaps = module.find_coverage_gaps(
        disk={"a/a-main.png"},
        produced={"a/a-main.png"},
        exempt={"b/gone.png": "理由"},
    )
    assert gaps == ["stale-exempt: b/gone.png"]


# ─────────────────────────── 7. check_homology 编排 ───────────────────────────


def test_check_homology_in_sync_is_ok_and_handles_identical_rewrite(tmp_path: Path) -> None:
    """脚本把图**原样重出**（字节相同）也必须算「有产出」→ ok，不误报 unregistered。"""
    module = _load_script()
    png = _png_bytes(8, 8, (7, 8, 9))
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (8, 8, (7, 8, 9))},
    )
    runner, calls = _fake_runner({"shot-alpha.cjs": {"alpha/alpha-main.png": png}})
    report = module.check_homology(str(root), runner=runner)
    assert calls == ["shot-alpha.cjs"]
    assert report.ok is True
    assert report.gaps == []
    assert "drift:" not in report.render()


def test_check_homology_reports_drift_with_page_state_px_maxdiff_bbox(tmp_path: Path) -> None:
    """变异自证的核心：改了 HTML（重出结果与已提交图不同）→ 不可 ok + 报告可归因。"""
    module = _load_script()
    block = {(x, y): (255, 0, 0) for x in range(5) for y in range(5)}
    drift_png = _png_bytes(8, 8, (0, 0, 0), overrides=block)
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (8, 8, (0, 0, 0))},
    )
    runner, _ = _fake_runner({"shot-alpha.cjs": {"alpha/alpha-main.png": drift_png}})
    report = module.check_homology(str(root), runner=runner)
    assert report.ok is False
    out = report.render()
    for token in ("alpha", "main", "px=25", "maxdiff=255", "bbox=(0, 0, 4, 4)"):
        assert token in out, f"报告缺 {token!r}：\n{out}"


def test_check_homology_noise_level_diff_is_ok(tmp_path: Path) -> None:
    """反例守护：噪声级差异（1 px / ±1 级）不误报。"""
    module = _load_script()
    noisy = _png_bytes(8, 8, (0, 0, 0), overrides={(4, 4): (0, 0, 1)})
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (8, 8, (0, 0, 0))},
    )
    runner, _ = _fake_runner({"shot-alpha.cjs": {"alpha/alpha-main.png": noisy}})
    report = module.check_homology(str(root), runner=runner)
    assert report.ok is True


def test_check_homology_unregistered_png_fails_without_script(tmp_path: Path) -> None:
    """无脚本页不得静默跳过：盘上有图、无脚本产出 → 缺口 → not ok。"""
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={
            "alpha/alpha-main.png": (4, 4, (1, 1, 1)),
            "orphan/orphan-main.png": (4, 4, (2, 2, 2)),
        },
    )
    runner, _ = _fake_runner(
        {"shot-alpha.cjs": {"alpha/alpha-main.png": _png_bytes(4, 4, (1, 1, 1))}}
    )
    report = module.check_homology(str(root), runner=runner)
    assert report.ok is False
    assert any(g.startswith("unregistered: orphan/orphan-main.png") for g in report.gaps)
    assert "unregistered: orphan/orphan-main.png" in report.render()


def test_check_homology_exempt_png_is_skipped_but_registered(tmp_path: Path) -> None:
    """豁免透明：登记在册的无脚本页 → 通过，且报告里回显豁免（不是静默跳过）。"""
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={
            "alpha/alpha-main.png": (4, 4, (1, 1, 1)),
            "orphan/orphan-main.png": (4, 4, (2, 2, 2)),
        },
        exempt=[{"png": "orphan/orphan-main.png", "reason": "历史手工资产，无出图脚本"}],
    )
    runner, _ = _fake_runner(
        {"shot-alpha.cjs": {"alpha/alpha-main.png": _png_bytes(4, 4, (1, 1, 1))}}
    )
    report = module.check_homology(str(root), runner=runner)
    assert report.ok is True
    assert "orphan/orphan-main.png" in report.render()


def test_check_homology_script_failure_is_not_ok(tmp_path: Path) -> None:
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (4, 4, (1, 1, 1))},
    )

    def failing(script: Path, repo_root: Path) -> int:
        return 1

    report = module.check_homology(str(root), runner=failing)
    assert report.ok is False
    assert any("shot-alpha.cjs" in s for s in report.script_failures)


def test_check_homology_leaves_working_tree_byte_identical(tmp_path: Path) -> None:
    """无副作用契约：门禁跑完必须把每张 PNG 还原为运行前字节。"""
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (8, 8, (0, 0, 0))},
    )
    png_path = root / "design" / "GUI" / "alpha" / "alpha-main.png"
    before = png_path.read_bytes()
    block = {(x, y): (255, 0, 0) for x in range(5) for y in range(5)}
    drift = _png_bytes(8, 8, (0, 0, 0), overrides=block)
    runner, _ = _fake_runner({"shot-alpha.cjs": {"alpha/alpha-main.png": drift}})
    report = module.check_homology(str(root), runner=runner)
    assert report.ok is False
    assert png_path.read_bytes() == before, "门禁必须还原工作树（无副作用）"


def test_scripts_run_after_mtime_normalization(tmp_path: Path) -> None:
    """产出集判据的可靠性前提（契约 §7 末条）：跑脚本前 PNG mtime 须归到「远古基准」。

    Windows/NTFS 文件时间粒度 ~15.6ms，同一刻度内的原样重出 mtime 不变（探针实证）→
    纯 mtime 判据会把「脚本原样重出」误报成 unregistered（假红）。本用例锁「归一化发生过」
    这一机制，防未来重构悄悄丢掉它。
    """
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (4, 4, (1, 1, 1))},
    )
    gui = root / "design" / "GUI"
    seen: list[int] = []

    def runner(script: Path, repo_root: Path) -> int:
        seen.extend(p.stat().st_mtime_ns for p in gui.glob("*/*.png"))
        return 0

    module.check_homology(str(root), runner=runner)
    assert seen, "runner 至少应看到一张 PNG"
    assert max(seen) < 1_000_000_000, f"PNG mtime 未归到远古基准（仍是真实时钟）：{seen}"


def test_working_tree_mtime_is_restored(tmp_path: Path) -> None:
    """归一化必须可逆：跑完还原原始 mtime（工作树元数据不得被门禁改脏）。"""
    module = _load_script()
    root = _make_repo(
        tmp_path,
        scripts={"shot-alpha.cjs": ["alpha/alpha-main.png"]},
        pngs={"alpha/alpha-main.png": (4, 4, (1, 1, 1))},
    )
    png = root / "design" / "GUI" / "alpha" / "alpha-main.png"
    before_mtime = png.stat().st_mtime_ns

    def runner(script: Path, repo_root: Path) -> int:
        png.write_bytes(png.read_bytes())  # 原样重出
        os.utime(png, ns=(5_000_000_000, 5_000_000_000))  # 明确改到与原始不同的值
        return 0

    module.check_homology(str(root), runner=runner)
    assert png.stat().st_mtime_ns == before_mtime, "门禁必须还原原始 mtime"


# ─────────────────────────── 8. main() 退出码 ───────────────────────────


def test_main_without_args_prints_usage_and_exits_two(monkeypatch, capsys) -> None:
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["check_gui_png_homology.py"])
    assert module.main() == 2
    assert "check_gui_png_homology" in capsys.readouterr().out


def test_main_missing_exempt_file_exits_two(monkeypatch, tmp_path: Path, capsys) -> None:
    """配置错（exempt 文件缺失）→ exit 2，不是「静默通过」。"""
    module = _load_script()
    (tmp_path / "design" / "GUI" / "_tools").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["check_gui_png_homology.py", str(tmp_path)])
    assert module.main() == 2
    assert "exempt" in capsys.readouterr().out.lower()


def test_main_passes_when_homology_ok(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_script()

    class _Report:
        ok = True

        def render(self) -> str:
            return "[check_gui_png_homology] OK"

    monkeypatch.setattr(module, "check_homology", lambda *a, **k: _Report())
    monkeypatch.setattr(sys, "argv", ["check_gui_png_homology.py", str(tmp_path)])
    assert module.main() == 0
    assert "OK" in capsys.readouterr().out


def test_main_fails_when_drift(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _load_script()

    class _Report:
        ok = False

        def render(self) -> str:
            return (
                "[check_gui_png_homology] drift: page=alpha state=main "
                "px=1 maxdiff=255 bbox=(2, 3, 2, 3)"
            )

    monkeypatch.setattr(module, "check_homology", lambda *a, **k: _Report())
    monkeypatch.setattr(sys, "argv", ["check_gui_png_homology.py", str(tmp_path)])
    assert module.main() == 1
    assert "drift" in capsys.readouterr().out


def test_main_survives_cp1252_stdout_with_cjk(monkeypatch, tmp_path: Path) -> None:
    """cp1252 stdout + 报告含 CJK → 不得抛 UnicodeEncodeError。"""
    module = _load_script()

    class _Report:
        ok = False

        def render(self) -> str:
            return "[check_gui_png_homology] unregistered: 手册/手册-main.png"

    monkeypatch.setattr(module, "check_homology", lambda *a, **k: _Report())
    _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_gui_png_homology.py", str(tmp_path)])
    assert module.main() == 1
