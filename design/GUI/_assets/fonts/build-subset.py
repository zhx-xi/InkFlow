"""构建原型自托管 serif 字体子集（#1460）。

为什么需要：``design/GUI/*/*.html`` 的 ``--font-serif`` 原先是本地字体栈
（"Noto Serif SC" / "Source Han Serif SC" / SimSun / 宋体 / Georgia），
在 CI runner 上解析到的字体与出图机器不同 → 层② PNG↔HTML 同源性门禁大面积假漂移
（PR #1459 实测 91/107）。把字体随仓库分发即可让渲染与字体环境无关。

做法（可复现，需网络）：
1. 从 Google Fonts CSS API 取「完整字体」——普通 UA 拿到的是按 unicode-range 切片的
   woff2，无法覆盖原型用到的全部符号；改用旧 UA 的 legacy 接口 ``/l/font?kit=`` 会返回
   **EOT**（Embedded OpenType，其 body 就是完整 SFNT/TTF）。
2. 剥离 EOT 头得到 TTF（解析头部而非搜 magic，避免误命中）。
3. 用 ``fonttools.subset`` 按「原型 HTML 实际出现的字符集」子集化 → woff2。
4. 重命名字体族为 ``InkFlow Serif``：与系统里可能安装的 "Noto Serif SC" 区分开，
   @font-face 若加载失败会立刻表现为回退到别的字体（而不是「看起来一样」，掩盖故障）。

用法（仓库根执行）::

    uv run --no-project --with fonttools --with brotli python \
        design/GUI/_assets/fonts/build-subset.py

新增原型文案若引入了字体里没有的字符，``ci_cd/tests/test_gui_selfhost_font.py``
的覆盖率用例会失败 → 重跑本脚本 + 重出受影响页面的 PNG。

字体来源与许可
--------------
- 字体：Noto Serif SC v2.003-H1（(c) 2017-2024 Adobe，(c) 2012 Google Inc.）
- 许可：SIL Open Font License 1.1（OFL-1.1）→ 见同目录 ``OFL.txt``
- 分发：Google Fonts（fonts.googleapis.com / fonts.gstatic.com）
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

# Google Fonts 对 legacy UA 返回 EOT；body 即完整 SFNT。
LEGACY_UA = "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)"
CSS_TMPL = "https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@{w}&display=swap"
WEIGHTS = (400, 600)
OUT_FAMILY = "InkFlow Serif"
MANIFEST_NAME = "subset-manifest.json"
# 保留全部 layout feature（kern/palt 等）以贴近完整字体的排版结果。
SUBSET_OPTS = [
    "--layout-features=*",
    "--name-IDs=*",
    "--name-legacy",
    "--notdef-glyph",
    "--notdef-outline",
]

_HERE = Path(__file__).resolve().parent
_PROTO_ROOT = _HERE.parents[1]  # design/GUI（_HERE = design/GUI/_assets/fonts）


def _fetch(url: str, ua: str | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _charset_from_prototypes() -> list[str]:
    """原型 HTML 里出现的全部字符（含 JS 字符串、注释里的非 ASCII 符号）。"""
    chars: set[str] = set()
    for html in sorted(_PROTO_ROOT.rglob("*.html")):
        chars |= set(html.read_text(encoding="utf-8"))
    return sorted(chars)


def _kit_url(weight: int) -> str:
    css = _fetch(CSS_TMPL.format(w=weight), ua=LEGACY_UA).decode("utf-8")
    match = re.search(r"src:\s*url\((https://fonts\.gstatic\.com/[^)]+)\)", css)
    if match is None:
        raise SystemExit(f"未能从 Google Fonts CSS 解析 wght={weight} 的字体 URL：\n{css}")
    return match.group(1)


def _strip_eot(data: bytes) -> bytes:
    """剥离 EOT 头，返回内嵌 SFNT 字节。

    EOT 头长度随内嵌的四个变长名（Family/Style/Version/FullName）变化，手写偏移容易出错
    （实测 Google 的 kit 头长 296B、非教科书布局）→ 改为扫描 SFNT magic 并**试解析**：
    第一个能被 ``TTFont`` 正常读出的偏移即字体数据起点。
    """
    for magic in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
        start = 0
        while (index := data.find(magic, start)) != -1:
            try:
                TTFont(io.BytesIO(data[index:]), lazy=True)
            except Exception:  # 解析失败即说明此处不是字体起点
                start = index + 1
                continue
            return data[index:]
    raise SystemExit("EOT body 中找不到可解析的 SFNT 数据")


def _rename(font: TTFont, family: str, subfamily: str) -> None:
    """改写 name 表，使族名唯一（避免与系统已装的 Noto Serif SC 混淆）。"""
    full = f"{family} {subfamily}".strip()
    ps = full.replace(" ", "")
    for record in font["name"].names:
        nid = record.nameID
        if nid in (1, 16):
            value = family
        elif nid == 2:
            value = "Regular"
        elif nid in (3, 17):
            value = f"{full};subset"
        elif nid == 4:
            value = full
        elif nid == 6:
            value = ps
        else:
            continue
        record.string = value


def _build(weight: int, chars: list[str]) -> bytes:
    ttf = _strip_eot(_fetch(_kit_url(weight), ua=LEGACY_UA))
    # recalcTimestamp=False：否则 head.modified 每次保存都写成「当前时间」→ 输出非确定
    # （实测同一 charset 连跑三次得到三个不同 SHA256，差异只在 head 表）。
    font = TTFont(io.BytesIO(ttf), recalcTimestamp=False)
    options = Options()
    options.parse_opts(SUBSET_OPTS)
    options.flavor = "woff2"
    subsetter = Subsetter(options=options)
    subsetter.populate(text="".join(chars))
    subsetter.subset(font)
    _rename(font, OUT_FAMILY, "Regular")
    buffer = io.BytesIO()
    font.flavor = "woff2"
    font.save(buffer)
    return buffer.getvalue()


def main() -> int:
    chars = _charset_from_prototypes()
    print(f"[build-subset] 原型字符集：{len(chars)} 个")
    files: dict[str, dict[str, int | str]] = {}
    missing: list[str] = []
    for weight in WEIGHTS:
        data = _build(weight, chars)
        dest = _HERE / f"inkflow-serif-{weight}.woff2"
        dest.write_bytes(data)
        subset = TTFont(io.BytesIO(data))
        cmap = subset.getBestCmap()
        covered = sum(1 for c in chars if ord(c) in cmap)
        missing = sorted(c for c in chars if ord(c) not in cmap)
        files[dest.name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "glyphs": subset["maxp"].numGlyphs,
            "covered": covered,
        }
        print(
            f"[build-subset] {dest.name}: {len(data):,} B, "
            f"glyphs={subset['maxp'].numGlyphs}, covered={covered}/{len(chars)}"
        )
    manifest = {
        "family": OUT_FAMILY,
        "source": "Noto Serif SC (static) v2.003-H1 — Google Fonts CDN legacy kit",
        "license": "OFL-1.1",
        "charset_sha256": hashlib.sha256("".join(chars).encode("utf-8")).hexdigest(),
        "charset_size": len(chars),
        "files": files,
        "missing_codepoints": [f"U+{ord(c):04X}" for c in missing],
    }
    (_HERE / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[build-subset] {MANIFEST_NAME} 已写出；缺字 {len(missing)} 个：{''.join(missing)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
