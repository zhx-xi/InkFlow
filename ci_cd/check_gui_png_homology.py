"""CI 护栏（#1330 层②）：``design/GUI/<page>/*.png`` 是否仍与「当前原型 HTML 重出的图」同源。

背景（#1363 / #1369 实测）：原型 HTML 改了，但同 PR 只重出「新增的状态图」，旧状态图被落下——
``writing/`` 11 张漂 4 张（8.9%–11.3% 像素差），其余 14 页 86 张漂 14 张（16.3%）。
图与 HTML 不同源 = 评审与 GUI 复验的依据失真。本门禁 = 防复发。

三层模型（职责互斥，务必别混淆）：
- 层① 原型目录 ↔ 页规格：``ci_cd/check_gui_spec_sync.py``（本门禁不碰）。
- 层② **原型 HTML ↔ 原型 PNG**：本文件（不依赖实现、不需固定数据种子）。
- 层③ 原型 ↔ 实现：#1452 长期观察，本门禁不做。

规则（判定）：
- 重跑 ``design/GUI/_tools/shot-*.cjs``（按文件名排序），与「已提交版」逐像素比对。
- 噪声与非漂移阈值（#1363/#1369 实测量级，均为**绝对**量）：最大通道差 ≤ ``NOISE_MAX_MAXDIFF``，
  或差异像素数 ≤ ``NOISE_MAX_PIXELS`` → NOISE（不报）；真漂移实测 maxdiff 34–215 → DRIFT。
- 尺寸不同（重出用了别的视口）→ DRIFT（不因「无法逐像素」而放过）。
- 无脚本产出的图必须登记在 ``ci_cd/gui_png_homology_exempt.json``；**未登记且无产出 = FAIL**
  （禁止静默跳过；静默跳过 = 假绿）。登记表腐烂（豁免项指向已不存在的图）同样报缺口。
- 运行是把图重出到工作树，故**跑完必须还原为运行前字节**（try/finally），保证可反复跑、工作树净。
- 产出集判据（mtime 变化）前先把每张图 mtime 归零到远古基准（``os.utime(ns=(0, 0))``）：
  NTFS 时间粒度 ~15.6ms → 同刻度原样重出不可见 → 故归零基准；还原在 finally（与字节还原一起）。

⚠️ **不校验什么**（能力边界，务必知晓）：
- 能查：有脚本覆盖的 PNG 是否仍与当前 HTML 同源；无脚本覆盖的图是否已显式登记豁免。
- **不校验**：像素归零只证「图 == 用当前 HTML 重出的图」，**不证图是对的**——重出后仍需人工/
  ``vision`` 目视复核语义。
- **不校验**：渲染环境差异（字体/GPU/合成取整）——判据是像素差，不是语义；跨机器渲染可能整体
  偏移，阈值外的环境性差异会报 DRIFT。
- **不校验**：**出图脚本没截到的画面**——层② 只比对「脚本实际渲染并截下的状态」。
  例如某页 `.page-lib` 是 `overflow-y:auto` 滚动容器、脚本滚到画布处截图，则**页头被滚出视口**，
  改它的文案不会让任何 PNG 产生差异（#1330 变异实测：knowledge 页 H1 文案改动 → 10 张图零差异）。
  判据是像素差，不是「HTML 有没有改」。
- **不校验**：层③ 原型 ↔ 实现一致性（那是 #1452）。
- **不校验**：页规格与原型目录的对应关系（那是层① ``check_gui_spec_sync.py``）。
- **不校验**：截图脚本自身的几何/文案断言是否过期——脚本断言由脚本自己的 exit code 表达，本门禁
  只把它当作「脚本失败」上报。
- **不校验**：脚本本次**新产出、但仓库未提交**的 PNG（无基线可比，不在此判定；它会留在工作树里
  由 ``git status`` 暴露）。仓库内既有的图若失去脚本产出，仍会被 ``unregistered:`` 捕获。

用法: python ci_cd/check_gui_png_homology.py <repo_root>
退出码 0 = 无漂移、无覆盖缺口、无脚本失败；1 = 存在漂移/缺口/脚本失败；
2 = 缺参数或配置错（``design/GUI`` 缺失 / exempt 登记表缺失或非法）。
"""

from __future__ import annotations

import contextlib
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# 阈值（#1363/#1369 实测）：最大通道差 ≤ 3 = 合成取整/抗锯齿；差异像素 ≤ 20 = 光标闪烁级
NOISE_MAX_MAXDIFF = 3
NOISE_MAX_PIXELS = 20
IDENTICAL, NOISE, DRIFT = "identical", "noise", "drift"

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_GUI_REL = ("design", "GUI")
_TOOLS_DIRNAME = "_tools"
_EXEMPT_REL = ("ci_cd", "gui_png_homology_exempt.json")
_SCRIPT_GLOB = "shot-*.cjs"


class PngFormatError(Exception):
    """PNG 不受支持或已损坏（非 8 位 RGB/RGBA、隔行、结构/压缩异常）。"""


class GateConfigError(Exception):
    """门禁配置错（``design/GUI`` 缺失、exempt 登记表缺失或非法）。"""


@dataclass(frozen=True)
class DiffResult:
    """两张同尺寸 PNG 的逐像素比对结果（尺寸不同则各数值退化）。"""

    pixels: int
    max_channel_diff: int
    bbox: tuple[int, int, int, int] | None  # (xmin, ymin, xmax, ymax)；无差异 None
    total_pixels: int
    same_size: bool


@dataclass
class HomologyReport:
    """一次 ``check_homology`` 的完整结果（drift/noise 均携带可归因 bbox）。"""

    script_failures: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    drift: list[tuple[str, DiffResult]] = field(default_factory=list)
    noise: list[tuple[str, DiffResult]] = field(default_factory=list)
    exempt: dict[str, str] = field(default_factory=dict)
    checked: int = 0
    total_pngs: int = 0
    script_count: int = 0
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        """无漂移 且 无覆盖缺口 且 无脚本失败 → 通过（噪声级差异不算漂移）。"""
        return not self.drift and not self.gaps and not self.script_failures

    def render(self) -> str:
        """人类可读报告：逐条列出漂移/噪声/缺口/豁免/脚本失败 + 汇总行。"""
        lines: list[str] = []
        lines.extend(_diff_line(DRIFT, rel, result) for rel, result in self.drift)
        lines.extend(_diff_line(NOISE, rel, result) for rel, result in self.noise)
        lines.extend(f"[check_gui_png_homology] gap: {gap}" for gap in self.gaps)
        lines.extend(
            f"[check_gui_png_homology] exempt: {png}  <- {self.exempt[png]}"
            for png in sorted(self.exempt)
        )
        lines.extend(
            f"[check_gui_png_homology] script failed: {failure}" for failure in self.script_failures
        )
        if self.ok:
            lines.append(
                f"[check_gui_png_homology] OK: {self.checked} png(s) homologous, "
                f"{len(self.exempt)} exempt, {self.script_count} script(s), "
                f"{self.duration_s:.1f}s"
            )
        else:
            lines.append(
                f"[check_gui_png_homology] FAIL: {len(self.drift)} drift, {len(self.gaps)} gap, "
                f"{len(self.script_failures)} script failure(s)"
            )
        return "\n".join(lines)


# ─────────────────────────── PNG 解析（纯标准库，无第三方依赖） ───────────────────────────


def _decode_png(data: bytes, label: str) -> tuple[int, int, bytes]:
    """把 PNG 字节解成 ``(width, height, rgb_bytes)``；仅支持 8 位 RGB/RGBA、非隔行。

    ``label`` 只用于报错定位（真实路径或 `<buffer>`）。RGBA 统一剥成 3 通道后再比
    （#1363 坑：新旧图色彩类型不同，硬断言 RGBA 会直接炸）。
    """
    if data[:8] != _PNG_SIG:
        raise PngFormatError(f"不是 PNG（签名不符）：{label}")
    width = height = depth = color = interlace = 0
    saw_ihdr = False
    idat = bytearray()
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if len(body) != length:
            raise PngFormatError(f"PNG chunk 截断：{label}")
        if ctype == b"IHDR":
            if len(body) < 13:
                raise PngFormatError(f"IHDR 长度异常：{label}")
            width, height, depth, color, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body[:13]
            )
            saw_ihdr = True
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if not saw_ihdr:
        raise PngFormatError(f"PNG 缺 IHDR：{label}")
    if depth != 8 or color not in (2, 6) or interlace != 0:
        raise PngFormatError(
            f"不支持的 PNG 形态（depth={depth} color={color} interlace={interlace}）：{label}"
        )
    bpp = 3 if color == 2 else 4
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PngFormatError(f"IDAT 解压失败：{label}") from exc
    stride = width * bpp
    if len(raw) < height * (stride + 1):
        raise PngFormatError(f"像素数据不足：{label}")
    out = bytearray()
    prior = bytearray(stride)
    off = 0
    for _ in range(height):
        ftype = raw[off]
        off += 1
        line = bytearray(raw[off : off + stride])
        off += stride
        _unfilter(ftype, line, prior, bpp, label)
        prior = line
        if bpp == 3:
            out += line
        else:
            for i in range(0, stride, 4):
                out += line[i : i + 3]
    return width, height, bytes(out)


def read_png_pixels(path: Path) -> tuple[int, int, bytes]:
    """读 PNG（仅 8 位 RGB/RGBA、非隔行），返回 ``(width, height, rgb_bytes)``。"""
    return _decode_png(Path(path).read_bytes(), str(path))


def _paeth(left: int, up: int, upleft: int) -> int:
    """PNG Paeth 预测器（filter type 4）。"""
    estimate = left + up - upleft
    dist_left = abs(estimate - left)
    dist_up = abs(estimate - up)
    dist_upleft = abs(estimate - upleft)
    if dist_left <= dist_up and dist_left <= dist_upleft:
        return left
    return up if dist_up <= dist_upleft else upleft


def _unfilter(ftype: int, line: bytearray, prior: bytearray, bpp: int, label: str) -> None:
    """就地反解 PNG 行滤波（0 None / 1 Sub / 2 Up / 3 Average / 4 Paeth）。"""
    size = len(line)
    if ftype == 0:
        return
    if ftype == 1:
        for i in range(bpp, size):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif ftype == 2:
        for i in range(size):
            line[i] = (line[i] + prior[i]) & 0xFF
    elif ftype == 3:
        for i in range(size):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + prior[i]) >> 1)) & 0xFF
    elif ftype == 4:
        for i in range(size):
            left = line[i - bpp] if i >= bpp else 0
            upleft = prior[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(left, prior[i], upleft)) & 0xFF
    else:
        raise PngFormatError(f"不支持的滤波类型 {ftype}：{label}")


def _compare_rgb(width: int, height: int, base: bytes, cand: bytes) -> DiffResult:
    """逐像素比 3 通道：统计不同像素数、最大通道差、差异 bbox。"""
    total = width * height
    pixels = 0
    max_channel_diff = 0
    xmin = ymin = 0
    xmax = ymax = -1
    for index in range(total):
        offset = index * 3
        diff = max(
            abs(base[offset] - cand[offset]),
            abs(base[offset + 1] - cand[offset + 1]),
            abs(base[offset + 2] - cand[offset + 2]),
        )
        if diff == 0:
            continue
        pixels += 1
        if diff > max_channel_diff:
            max_channel_diff = diff
        x = index % width
        y = index // width
        if pixels == 1:
            xmin, ymin, xmax, ymax = x, y, x, y
        else:
            xmin, ymin = min(xmin, x), min(ymin, y)
            xmax, ymax = max(xmax, x), max(ymax, y)
    bbox = None if pixels == 0 else (xmin, ymin, xmax, ymax)
    return DiffResult(pixels, max_channel_diff, bbox, total, True)


def _png_size_from_ihdr(data: bytes, label: str) -> tuple[int, int]:
    """只解析 IHDR 取 ``(width, height)``；仍校验签名 + depth/color/interlace 合法。

    供「字节相同短路」用：同字节的图无需反滤波即可确认同尺寸同内容，但格式契约
    （``PngFormatError``）不得因此退化，故仍走一遍头部校验。
    """
    if data[:8] != _PNG_SIG:
        raise PngFormatError(f"不是 PNG（签名不符）：{label}")
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        if ctype == b"IHDR":
            body = data[pos + 8 : pos + 8 + length]
            if len(body) < 13:
                raise PngFormatError(f"IHDR 长度异常：{label}")
            width, height, depth, color, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body[:13]
            )
            if depth != 8 or color not in (2, 6) or interlace != 0:
                raise PngFormatError(
                    f"不支持的 PNG 形态（depth={depth} color={color} "
                    f"interlace={interlace}）：{label}"
                )
            return width, height
        pos += 12 + length
    raise PngFormatError(f"PNG 缺 IHDR：{label}")


def _diff_buffers(base_bytes: bytes, cand_bytes: bytes, label: str) -> DiffResult:
    """按字节缓冲比对两张 PNG（私有核心；``diff_png`` 是它的 Path 版包装）。

    #1369 实测重出逐字节确定（同步态 107/107 字节相同）——字节相同即直接短路返回等值结果，
    不再反滤波解码（正常态整仓解码纯属浪费）；尺寸仅从 IHDR 取，格式仍校验。
    """
    if base_bytes == cand_bytes:
        width, height = _png_size_from_ihdr(base_bytes, label)
        return DiffResult(0, 0, None, width * height, True)
    w1, h1, p1 = _decode_png(base_bytes, label)
    w2, h2, p2 = _decode_png(cand_bytes, label)
    if (w1, h1) != (w2, h2):
        return DiffResult(0, 0, None, w2 * h2, False)
    return _compare_rgb(w2, h2, p1, p2)


def diff_png(baseline: Path, candidate: Path) -> DiffResult:
    """比对两张 PNG；尺寸不同 → ``same_size=False``（无法逐像素，交由 classify 判 DRIFT）。"""
    return _diff_buffers(Path(baseline).read_bytes(), Path(candidate).read_bytes(), str(candidate))


def classify_diff(result: DiffResult) -> str:
    """判定顺序固定：尺寸不同 → DRIFT；无差异 → IDENTICAL；噪声级 → NOISE；否则 DRIFT。

    噪声级 = 最大通道差 ≤ ``NOISE_MAX_MAXDIFF``，或差异像素 ≤ ``NOISE_MAX_PIXELS``——两个
    阈值都是**绝对**量，不叠加比例/百分比守卫（#1363/#1369 实测量级即在真实图上取的绝对值）。
    """
    if not result.same_size:
        return DRIFT
    if result.pixels == 0:
        return IDENTICAL
    if result.max_channel_diff <= NOISE_MAX_MAXDIFF:
        return NOISE
    if result.pixels <= NOISE_MAX_PIXELS:
        return NOISE
    return DRIFT


# ─────────────────────────── 豁免登记与覆盖缺口 ───────────────────────────


def load_exempt(path: Path) -> dict[str, str]:
    """读 exempt 登记表，返回 ``{png 相对路径: 理由}``；结构非法 → ``ValueError``。"""
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"exempt 登记表不是合法 JSON：{path}") from exc
    if not isinstance(payload, dict) or "exempt" not in payload:
        raise ValueError(f"exempt 登记表须为含 'exempt' 键的对象：{path}")
    entries = payload["exempt"]
    if not isinstance(entries, list):
        # 契约（test_load_exempt_rejects_malformed）要求结构非法一律 ValueError，故不用 TypeError
        raise ValueError(f"exempt 必须是列表：{path}")  # noqa: TRY004
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"exempt 条目须为对象：{entry!r}")  # noqa: TRY004
        png = entry.get("png")
        reason = entry.get("reason")
        if not isinstance(png, str) or not png or not isinstance(reason, str) or not reason:
            raise ValueError(f"exempt 条目须含非空 'png' 与 'reason'：{entry!r}")
        result[png] = reason
    return result


def find_coverage_gaps(*, disk: set[str], produced: set[str], exempt: dict[str, str]) -> list[str]:
    """返回覆盖缺口：``unregistered:``（盘上有、无产出、未登记）+ ``stale-exempt:``（登记腐烂）。"""
    gaps: list[str] = []
    for png in sorted(disk - produced - set(exempt)):
        gaps.append(f"unregistered: {png}")
    for png in sorted(set(exempt) - disk):
        gaps.append(f"stale-exempt: {png}")
    return gaps


# ─────────────────────────── 编排 ───────────────────────────


def _page_state(rel: str) -> tuple[str, str]:
    """由 ``<page>/<page>-<state>.png`` 拆出 ``(page, state)``。

    只剥页名前缀，文件名里其余连字符不参与解析（状态名原样保留）。
    """
    page, _, name = rel.partition("/")
    stem = name[:-4] if name.endswith(".png") else name
    prefix = f"{page}-"
    state = stem[len(prefix) :] if stem.startswith(prefix) else stem
    return page, state


def _diff_line(kind: str, rel: str, result: DiffResult) -> str:
    """渲染一条漂移/噪声行（bbox 逗号后有一个空格，便于逐字验收）。"""
    page, state = _page_state(rel)
    pct = (result.pixels / result.total_pixels * 100.0) if result.total_pixels else 0.0
    if result.bbox is None:
        bbox = "None"
    else:
        bbox = "(" + ", ".join(str(value) for value in result.bbox) + ")"
    return (
        f"[check_gui_png_homology] {kind}: page={page} state={state}  "
        f"px={result.pixels} ({pct:.4f}%)  maxdiff={result.max_channel_diff}  bbox={bbox}"
    )


def _list_pngs(gui_root: Path) -> list[Path]:
    """``design/GUI/<page>/*.png``（只一层 page 子目录；排除 ``_tools``）。"""
    if not gui_root.is_dir():
        return []
    found: list[Path] = []
    for page_dir in sorted(gui_root.iterdir()):
        if not page_dir.is_dir() or page_dir.name.startswith("_") or page_dir.name.startswith("."):
            continue
        found.extend(sorted(page_dir.glob("*.png")))
    return found


def _rel_pngs(gui_root: Path) -> dict[str, Path]:
    """``{相对 design/GUI 的路径: 绝对路径}``，键用 POSIX 分隔符。"""
    return {png.relative_to(gui_root).as_posix(): png for png in _list_pngs(gui_root)}


def _read_png_bytes(gui_root: Path) -> dict[str, bytes]:
    """``{相对路径: 字节}``（基线/候选的字节缓冲快照）。"""
    return {rel: png.read_bytes() for rel, png in _rel_pngs(gui_root).items()}


def _stat_snapshot(gui_root: Path) -> dict[str, tuple[int, int, int]]:
    """``{相对路径: (mtime_ns, size, ctime_ns)}``——脚本运行前后的产出判据。"""
    snapshot: dict[str, tuple[int, int, int]] = {}
    for rel, png in _rel_pngs(gui_root).items():
        stat = png.stat()
        snapshot[rel] = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
    return snapshot


def _capture_mtimes(gui_root: Path) -> dict[str, tuple[int, int]]:
    """记录每张 PNG 的 ``(st_atime_ns, st_mtime_ns)``，供归一化后在 finally 还原原始时间戳。"""
    times: dict[str, tuple[int, int]] = {}
    for rel, png in _rel_pngs(gui_root).items():
        stat = png.stat()
        times[rel] = (stat.st_atime_ns, stat.st_mtime_ns)
    return times


def _normalize_mtimes(gui_root: Path) -> None:
    """把每张 PNG 的 atime/mtime 归到远古基准 ``ns=(0, 0)``。

    产出集判据是脚本运行前后的 mtime 变化，而 Windows/NTFS 时间粒度 ~15.6ms：同一刻度内的
    原样重出 mtime 不变 → 纯 mtime 判据会把「脚本原样重出」误报成 unregistered（假红）；
    归零基准后任何真实写入（playwright 截图 / node 复制）都远晚于基准，判据确定可靠。
    原始值由 ``_capture_mtimes`` 记录、``_restore_mtimes`` 在 finally 还原。
    """
    for _rel, png in _rel_pngs(gui_root).items():
        os.utime(png, ns=(0, 0))


def _restore_mtimes(gui_root: Path, before_times: dict[str, tuple[int, int]]) -> None:
    """还原每张 PNG 运行前的 ``(atime_ns, mtime_ns)``（含被删后重建的图）。

    与 ``_restore`` 同为尽力而为：还原失败不崩门禁，真脏由调用方随后的 git status 暴露。
    """
    for rel, (atime_ns, mtime_ns) in before_times.items():
        with contextlib.suppress(OSError):
            os.utime(gui_root / rel, ns=(atime_ns, mtime_ns))


def _default_runner(script: Path, repo_root: Path) -> int:
    """默认 runner：``node <脚本相对路径>``（cwd = repo_root）；仅失败时转印输出便于归因。"""
    rel = os.path.relpath(str(script), str(repo_root)).replace("\\", "/")
    proc = subprocess.run(
        ["node", rel],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
        if proc.stderr:
            print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    return proc.returncode


def _restore(gui_root: Path, before_bytes: dict[str, bytes]) -> None:
    """把每张 PNG 还原为运行前字节（含被脚本删除的图重建），保证工作树不被门禁改脏。"""
    for rel, data in before_bytes.items():
        path = gui_root / rel
        try:
            current = path.read_bytes()
        except OSError:
            current = None
        if current != data:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError:
                pass  # 还原是尽力而为；失败会体现在调用方随后的 git status，而非崩门禁


def check_homology(
    repo_root: str, *, runner: Callable[[Path, Path], int] | None = None
) -> HomologyReport:
    """重跑 ``shot-*.cjs`` 并与已提交 PNG 逐像素比对；跑完还原工作树。"""
    root = Path(repo_root)
    gui_root = root.joinpath(*_GUI_REL)
    if not gui_root.is_dir():
        raise GateConfigError(f"配置错：找不到原型目录 design/GUI（{gui_root}）")
    tools_dir = gui_root / _TOOLS_DIRNAME
    scripts = sorted(tools_dir.glob(_SCRIPT_GLOB)) if tools_dir.is_dir() else []
    exempt_path = root.joinpath(*_EXEMPT_REL)
    try:
        exempt = load_exempt(exempt_path)
    except (ValueError, OSError) as exc:
        raise GateConfigError(f"配置错：exempt 登记表不可用（{exempt_path}）：{exc}") from exc

    run = runner or _default_runner
    started = time.perf_counter()

    before_bytes = _read_png_bytes(gui_root)
    before_times = _capture_mtimes(gui_root)
    script_failures: list[str] = []
    produced: set[str] = set()
    try:
        _normalize_mtimes(gui_root)
        for script in scripts:
            pre = _stat_snapshot(gui_root)
            exit_code = run(script, root)
            if exit_code != 0:
                script_failures.append(f"{script.name} (exit {exit_code})")
            post = _stat_snapshot(gui_root)
            for rel, signature in post.items():
                if rel not in pre or pre[rel] != signature:
                    produced.add(rel)
        after_bytes = _read_png_bytes(gui_root)
        disk = set(after_bytes)
        drift: list[tuple[str, DiffResult]] = []
        noise: list[tuple[str, DiffResult]] = []
        checked = 0
        for rel in sorted(produced & disk):
            baseline = before_bytes.get(rel)
            if baseline is None:
                continue  # 本次新产出、仓库未提交的图：无基线可逐像素比，不在此处判定
            checked += 1
            result = _diff_buffers(baseline, after_bytes[rel], rel)
            verdict = classify_diff(result)
            if verdict == DRIFT:
                drift.append((rel, result))
            elif verdict == NOISE:
                noise.append((rel, result))
        gaps = find_coverage_gaps(disk=disk, produced=produced, exempt=exempt)
    finally:
        _restore(gui_root, before_bytes)
        _restore_mtimes(gui_root, before_times)

    return HomologyReport(
        script_failures=script_failures,
        gaps=gaps,
        drift=drift,
        noise=noise,
        exempt=exempt,
        checked=checked,
        total_pngs=len(before_bytes),
        script_count=len(scripts),
        duration_s=time.perf_counter() - started,
    )


def main() -> int:
    # Windows CI stdout 默认 cp1252：报告行含中文路径时直写会抛 UnicodeEncodeError。
    # sys.stdout.reconfigure(errors="replace") 官方兜底：任意编码不崩，非 ASCII 显示为 ?
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    try:
        report = check_homology(sys.argv[1])
    except (GateConfigError, OSError) as exc:
        print(f"[check_gui_png_homology] 配置错（design/GUI 或 exempt 登记表）：{exc}")
        return 2
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
