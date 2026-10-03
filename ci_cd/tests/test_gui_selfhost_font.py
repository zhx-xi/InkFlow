"""契约测试（#1460）：原型 serif 字体自托管 —— 让层② PNG↔HTML 同源性门禁可进 CI。

背景（为什么需要自托管）
------------------------
``design/GUI/<page>/<page>.html`` 的 ``--font-serif`` 原先是**本机字体栈**
（``"Noto Serif SC","Source Han Serif SC","SimSun","宋体",Georgia,serif``）。
字体栈是机器相关的：CI runner 上解析到的字体与出图机器不同 → 字形栅格化不同
→ ``ci_cd/check_gui_png_homology.py``（层②，判据 = 像素差）大面积**假漂移**
（PR #1459 的 CI 实测 91/107 漂移、maxdiff 129–215）。

修法 = 把 serif 字体子集随仓库分发（``design/GUI/_assets/fonts/``），
``--font-serif`` 首选项指向它，原字体栈整体保留在后面兜底。

契约（以本文件断言为准）
------------------------
1. 资产：``inkflow-serif-{400,600}.woff2`` 已入库、是真 woff2（``wOF2`` magic）、
   体积在预算内；``OFL.txt`` 为 SIL Open Font License 原文。
2. 每个原型 HTML **自带** ``@font-face``（族名 = ``InkFlow Serif``，400 与 600 各一条，
   ``src`` 指向相对路径 ``../_assets/fonts/inkflow-serif-<w>.woff2``）；
   ``@font-face`` 里**不得**出现 http(s) 地址（离线确定性：渲染不依赖网络）。
3. 每个原型 HTML 的 ``--font-serif:`` 首选项 = ``"InkFlow Serif"``，
   且原字体栈**原样保留**为后续兜底项。
4. 覆盖：原型字符集的 SHA256 与 ``subset-manifest.json`` 一致（改了文案就要重跑
   ``build-subset.py``），且「字体不含的码位」与文档化的系统兜底集合**完全一致**
   （不多不少——多一个 = 悄悄放宽，少一个 = 清单过期）。
5. ``subset-manifest.json`` 里每个 woff2 的字节数/SHA256 与磁盘一致
   （防「换了字体文件但没重跑构建」）。

⚠️ 本契约**不校验**渲染结果（那由层② ``check_gui_png_homology.py`` 用像素差判）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTO_ROOT = REPO_ROOT / "design" / "GUI"
FONT_DIR = PROTO_ROOT / "_assets" / "fonts"
MANIFEST_PATH = FONT_DIR / "subset-manifest.json"

SELFHOST_FAMILY = "InkFlow Serif"
WEIGHTS = (400, 600)
# 原字体栈（自托管字体之后的兜底项，必须原样保留）
FALLBACK_STACK = (
    '"Noto Serif SC"',
    '"Source Han Serif SC"',
    '"SimSun"',
    '"宋体"',
    "Georgia",
    "serif",
)
FONT_URL_TMPL = "../_assets/fonts/inkflow-serif-{weight}.woff2"

MIN_FONT_BYTES = 8 * 1024
MAX_FONT_BYTES = 512 * 1024
# 完整 Noto Serif SC 本身不含、由系统字体兜底的码位（README「残留的机器相关性」节）：
# 换行 + 变体选择符 + ▸▾（详情/折叠三角）+ 5 个 emoji。
DOCUMENTED_FALLBACK_CODEPOINTS = frozenset(
    {"U+000A", "U+25B8", "U+25BE", "U+2705", "U+FE0F", "U+1F4CE", "U+1F534", "U+1F5FA", "U+1F9E0"}
)

_FONT_SERIF_RE = re.compile(r"--font-serif\s*:\s*([^;]+);")
_FACE_BLOCK_RE = re.compile(r"@font-face\s*\{(.*?)\}", re.DOTALL)


def _prototypes() -> list[Path]:
    """``design/GUI/**/*.html``（与 ``build-subset.py`` 的字符集口径一致）。"""
    return sorted(PROTO_ROOT.rglob("*.html"))


def _prototype_charset() -> set[str]:
    """原型 HTML 里出现过的全部字符（含 JS 字符串与文案）。"""
    chars: set[str] = set()
    for html in _prototypes():
        chars |= set(html.read_text(encoding="utf-8"))
    return chars


def _face_blocks(html: str) -> list[dict[str, str]]:
    """把 HTML 里的 ``@font-face`` 块解析成 ``{family, weight, src}``。"""
    faces = []
    for body in _FACE_BLOCK_RE.findall(html):
        family = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)", body)
        weight = re.search(r"font-weight\s*:\s*([^;]+)", body)
        src = re.search(r"src\s*:\s*([^;]+)", body)
        faces.append(
            {
                "family": (family.group(1) if family else "").strip(),
                "weight": (weight.group(1) if weight else "").strip(),
                "src": (src.group(1) if src else "").strip(),
            }
        )
    return faces


def test_prototype_pages_are_discovered() -> None:
    """守卫测试自身：页面集非空（否则下面所有断言会静默空转 = 假绿）。"""
    pages = _prototypes()
    assert len(pages) >= 15, f"只发现 {len(pages)} 个原型页 → 路径假设失效，检查本文件"
    assert all(p.parent.name for p in pages)


def test_font_assets_are_committed_woff2_in_budget() -> None:
    for weight in WEIGHTS:
        path = FONT_DIR / f"inkflow-serif-{weight}.woff2"
        assert path.is_file(), f"缺字体资产 {path.relative_to(REPO_ROOT)}"
        data = path.read_bytes()
        assert data[:4] == b"wOF2", f"{path.name} 不是 woff2（magic={data[:4]!r}）"
        assert MIN_FONT_BYTES <= len(data) <= MAX_FONT_BYTES, (
            f"{path.name} 体积 {len(data)} B 超出预算 [{MIN_FONT_BYTES}, {MAX_FONT_BYTES}]"
            "（过小=子集不完整，过大=忘了子集化）"
        )


def test_license_file_is_sil_open_font_license() -> None:
    text = (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in text.upper(), "缺 OFL 许可原文（Noto Serif SC 为 OFL-1.1）"


def test_every_prototype_declares_selfhost_faces() -> None:
    """每个原型声明 ``InkFlow Serif`` 的 400/600 @font-face，src 为相对路径、无网络地址。"""
    for page in _prototypes():
        html = page.read_text(encoding="utf-8")
        faces = _face_blocks(html)
        mine = [f for f in faces if f["family"].strip("'\"") == SELFHOST_FAMILY]
        assert mine, f"{page.relative_to(REPO_ROOT)} 未声明 {SELFHOST_FAMILY!r} 的 @font-face"
        by_weight = {f["weight"]: f["src"] for f in mine}
        for weight in WEIGHTS:
            assert str(weight) in by_weight, (
                f"{page.relative_to(REPO_ROOT)} 缺 {SELFHOST_FAMILY} weight={weight} 的 @font-face"
            )
            expected = FONT_URL_TMPL.format(weight=weight)
            assert expected in by_weight[str(weight)], (
                f"{page.relative_to(REPO_ROOT)} weight={weight} 的 src 未指向 {expected}："
                f"{by_weight[str(weight)]!r}"
            )
        for face in faces:
            assert not re.search(r"https?://", face["src"]), (
                f"{page.relative_to(REPO_ROOT)} 的 @font-face src 含网络地址 → 渲染依赖网络："
                f"{face['src']!r}"
            )


def test_font_serif_prefers_selfhost_and_keeps_fallback() -> None:
    """``--font-serif`` 首选项 = 自托管族；原字体栈原样保留为兜底项。"""
    for page in _prototypes():
        html = page.read_text(encoding="utf-8")
        match = _FONT_SERIF_RE.search(html)
        assert match, f"{page.relative_to(REPO_ROOT)} 未定义 --font-serif"
        families = [item.strip() for item in match.group(1).split(",")]
        expected = [f'"{SELFHOST_FAMILY}"', *FALLBACK_STACK]
        assert families == expected, (
            f"{page.relative_to(REPO_ROOT)} 的 --font-serif 应为 {expected}，实际 {families}"
        )


def test_selfhost_family_is_distinct_from_system_stack() -> None:
    """族名不得与兜底链里的系统字体同名：否则 @font-face 加载失败会「看起来一样」，把故障藏起来。"""
    assert f'"{SELFHOST_FAMILY}"' not in FALLBACK_STACK


def test_subset_manifest_matches_committed_assets() -> None:
    """清单与磁盘资产一致（防「改了字体文件/原型文案却没重跑构建」）。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256("".join(sorted(_prototype_charset())).encode("utf-8")).hexdigest()
    assert manifest["charset_sha256"] == expected_sha, (
        "原型字符集与 subset-manifest.json 不一致 → 请重跑 design/GUI/_assets/fonts/build-subset.py"
    )
    assert manifest["charset_size"] == len(_prototype_charset())
    assert manifest["family"] == SELFHOST_FAMILY
    assert manifest["license"] == "OFL-1.1"
    for name, info in manifest["files"].items():
        data = (FONT_DIR / name).read_bytes()
        assert info["bytes"] == len(data), f"{name} 字节数与清单不符 → 资产被替换但未重跑构建"
        assert info["sha256"] == hashlib.sha256(data).hexdigest(), f"{name} SHA256 与清单不符"


def test_subset_coverage_matches_documented_fallback() -> None:
    """字体不含的码位必须与文档化的系统兜底集合**完全一致**（多/少都算清单腐败）。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    missing = frozenset(manifest["missing_codepoints"])
    extra = sorted(missing - DOCUMENTED_FALLBACK_CODEPOINTS)
    absent = sorted(DOCUMENTED_FALLBACK_CODEPOINTS - missing)
    assert missing == DOCUMENTED_FALLBACK_CODEPOINTS, (
        "字体缺字集合与文档化的系统兜底集合不一致。\n"
        f"  清单多出（覆盖退化 / 新字符未入库）：{extra}\n"
        f"  清单少了（兜底说明过期）：{absent}"
    )
    # 清单覆盖数 = 字符集 - 兜底集（防止 covered 字段被手改而字符集未变）
    assert all(
        info["covered"] == manifest["charset_size"] - len(missing)
        for info in manifest["files"].values()
    )
