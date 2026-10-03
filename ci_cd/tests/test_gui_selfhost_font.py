"""契约测试（#1460）：原型字体自托管（serif 主栈 + sans 兜底层）—— 让层② PNG↔HTML 门禁可进 CI。

背景（为什么需要自托管）
------------------------
``design/GUI/<page>/<page>.html`` 的两个字体 token 原先是**本机字体栈**——
``--font-serif:"Noto Serif SC","Source Han Serif SC","SimSun","宋体",Georgia,serif``、
``--font-ui:"PingFang SC","Microsoft YaHei","Noto Sans SC","Segoe UI",sans-serif``。
字体栈是机器相关的：CI runner 上解析到的字体与出图机器不同 → 字形栅格化不同
→ ``ci_cd/check_gui_png_homology.py``（层②，判据 = 像素差）**假漂移**：

- PR #1459 的 CI 实测 **91/107 漂移**（bbox 一律自 ``(44, 16)`` 起、maxdiff 129–215）= serif 栈；
- #1460 首轮修复后仍剩 **2/107**（world-plan-b / world-plan-c 的评审注解行）
  = ``--font-ui`` 里的 ``"Noto Sans SC"`` 是**本机专有条目**：本机装了它，CI 没有
  → ``↔``/``⇒``/``⚠`` 这 3 个 Microsoft YaHei 缺的字形两端解析不同（13px vs 11px）
  → 整行换行不同。

修法 = 把两个 token 里「机器相关的那一层」换成随仓库分发的子集：
``--font-serif`` 首选项 = ``InkFlow Serif``；``--font-ui`` 在 ``Microsoft YaHei`` 之后、
``"Noto Sans SC"`` **之前**插入 ``InkFlow Sans``（保留原字体链其余部分兜底）。

契约（以本文件断言为准）
------------------------
1. 资产：``inkflow-{serif,sans}-{400,600}.woff2`` 已入库、是真 woff2（``wOF2`` magic）、
   体积在预算内；``OFL.txt`` 为 SIL Open Font License 原文。
2. 每个原型 HTML **自带** ``@font-face``（两个族各 400/600，``src`` 指向相对路径
   ``../_assets/fonts/<file>.woff2``）；``@font-face`` 里**不得**出现 http(s) 地址
   （离线确定性：渲染不依赖网络）。
3. 每个原型 HTML 的两个字体 token 写法固定：
   ``--font-serif`` 首选项 = ``InkFlow Serif`` 且原字体栈原样保留；
   ``--font-ui`` 在 ``Microsoft YaHei`` 与 ``"Noto Sans SC"`` 之间插入 ``InkFlow Sans``。
4. 覆盖：原型字符集的 SHA256 与 ``subset-manifest.json`` 一致（改了文案就要重跑
   ``build-subset.py``）；**每个族**的「字体不含的码位」与文档化的系统兜底集合**完全一致**
   （多一个 = 悄悄放宽，少一个 = 清单过期）。
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

WEIGHTS = (400, 600)
# 两个 token 的期望形态（顺序 load-bearing）
SERIF_STACK = (
    '"InkFlow Serif"',
    '"Noto Serif SC"',
    '"Source Han Serif SC"',
    '"SimSun"',
    '"宋体"',
    "Georgia",
    "serif",
)
SANS_STACK = (
    '"PingFang SC"',
    '"Microsoft YaHei"',
    '"InkFlow Sans"',
    '"Noto Sans SC"',
    '"Segoe UI"',
    "sans-serif",
)
# token 名 → (自托管族名, woff2 文件名模板)
FAMILIES = {
    "serif": ("InkFlow Serif", "inkflow-serif-{weight}.woff2"),
    "sans": ("InkFlow Sans", "inkflow-sans-{weight}.woff2"),
}
TOKEN_STACKS = {"--font-serif": SERIF_STACK, "--font-ui": SANS_STACK}

MIN_FONT_BYTES = 4 * 1024
MAX_FONT_BYTES = 512 * 1024
# 完整 Noto Serif SC / Noto Sans SC 本身不含、由系统字体兜底的码位
# （README「残留的机器相关性」节）：换行 + 变体选择符 + ▸▾（详情/折叠三角）+ 5 个 emoji。
DOCUMENTED_FALLBACK_CODEPOINTS = frozenset(
    {"U+000A", "U+25B8", "U+25BE", "U+2705", "U+FE0F", "U+1F4CE", "U+1F534", "U+1F5FA", "U+1F9E0"}
)

_TOKEN_RE = re.compile(r"(--font-(?:serif|ui))\s*:\s*([^;]+);")
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
                "family": (family.group(1) if family else "").strip().strip("'\""),
                "weight": (weight.group(1) if weight else "").strip(),
                "src": (src.group(1) if src else "").strip(),
            }
        )
    return faces


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_prototype_pages_are_discovered() -> None:
    """守卫测试自身：页面集非空（否则下面所有断言会静默空转 = 假绿）。"""
    pages = _prototypes()
    assert len(pages) >= 15, f"只发现 {len(pages)} 个原型页 → 路径假设失效，检查本文件"


def test_font_assets_are_committed_woff2_in_budget() -> None:
    for _key, (_family, tmpl) in FAMILIES.items():
        for weight in WEIGHTS:
            path = FONT_DIR / tmpl.format(weight=weight)
            assert path.is_file(), f"缺字体资产 {path.relative_to(REPO_ROOT)}"
            data = path.read_bytes()
            assert data[:4] == b"wOF2", f"{path.name} 不是 woff2（magic={data[:4]!r}）"
            assert MIN_FONT_BYTES <= len(data) <= MAX_FONT_BYTES, (
                f"{path.name} 体积 {len(data)} B 超出预算 [{MIN_FONT_BYTES}, {MAX_FONT_BYTES}]"
                "（过小=子集不完整，过大=忘了子集化）"
            )


def test_license_file_is_sil_open_font_license() -> None:
    text = (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in text.upper(), "缺 OFL 许可原文（Noto 系为 OFL-1.1）"


def test_every_prototype_declares_selfhost_faces() -> None:
    """每个原型声明两个自托管族的 400/600 @font-face，src 为相对路径、无网络地址。"""
    for page in _prototypes():
        html = page.read_text(encoding="utf-8")
        faces = _face_blocks(html)
        for key, (family, tmpl) in FAMILIES.items():
            mine = [f for f in faces if f["family"] == family]
            assert mine, f"{page.relative_to(REPO_ROOT)} 未声明 {family!r}（{key}）的 @font-face"
            by_weight = {f["weight"]: f["src"] for f in mine}
            for weight in WEIGHTS:
                assert str(weight) in by_weight, (
                    f"{page.relative_to(REPO_ROOT)} 缺 {family} weight={weight} 的 @font-face"
                )
                expected = f"../_assets/fonts/{tmpl.format(weight=weight)}"
                assert expected in by_weight[str(weight)], (
                    f"{page.relative_to(REPO_ROOT)} {family} weight={weight} 的 src 未指向 "
                    f"{expected}：{by_weight[str(weight)]!r}"
                )
        for face in faces:
            assert not re.search(r"https?://", face["src"]), (
                f"{page.relative_to(REPO_ROOT)} 的 @font-face src 含网络地址 → 渲染依赖网络："
                f"{face['src']!r}"
            )


def test_font_tokens_prefer_selfhost_and_keep_fallback() -> None:
    """两个字体 token 的栈形固定：自托管族在「机器相关那一层」的位置上，其余原样保留。"""
    for page in _prototypes():
        html = page.read_text(encoding="utf-8")
        found = {
            m.group(1): [x.strip() for x in m.group(2).split(",")] for m in _TOKEN_RE.finditer(html)
        }
        for token, expected in TOKEN_STACKS.items():
            assert token in found, f"{page.relative_to(REPO_ROOT)} 未定义 {token}"
            assert found[token] == list(expected), (
                f"{page.relative_to(REPO_ROOT)} 的 {token} 不符："
                f"期望 {list(expected)}；实际 {found[token]}"
            )


def test_selfhost_families_are_distinct_from_system_stack() -> None:
    """族名不得与兜底链里的系统字体同名：否则 @font-face 加载失败会「看起来一样」，把故障藏起来。"""
    for key, (family, _tmpl) in FAMILIES.items():
        quoted = f'"{family}"'
        stack = SERIF_STACK if key == "serif" else SANS_STACK
        selfhost, fallbacks = [f for f in stack if f == quoted], [f for f in stack if f != quoted]
        assert selfhost == [quoted], f"{key} 的自托管族应在栈中恰好出现一次：{stack}"
        assert quoted not in fallbacks, f"{key} 族名与系统兜底项重名 → 加载失败会藏故障"


def test_subset_manifest_matches_committed_assets() -> None:
    """清单与磁盘资产一致（防「改了字体文件/原型文案却没重跑构建」）。"""
    manifest = _manifest()
    charset = _prototype_charset()
    expected_sha = hashlib.sha256("".join(sorted(charset)).encode("utf-8")).hexdigest()
    assert manifest["charset_sha256"] == expected_sha, (
        "原型字符集与 subset-manifest.json 不一致 → 请重跑 design/GUI/_assets/fonts/build-subset.py"
    )
    assert manifest["charset_size"] == len(charset)
    fonts = manifest["fonts"]
    assert isinstance(fonts, dict) and set(fonts) == set(FAMILIES)
    for key, (family, _tmpl) in FAMILIES.items():
        entry = fonts[key]
        assert entry["family"] == family
        assert entry["license"] == "OFL-1.1"
        assert entry["source"], f"{key} 缺来源说明"
        assert set(entry["files"]) == {f"inkflow-{key}-{w}.woff2" for w in WEIGHTS}
        for name, info in entry["files"].items():
            data = (FONT_DIR / name).read_bytes()
            assert info["bytes"] == len(data), f"{name} 字节数与清单不符 → 资产被替换但未重跑构建"
            assert info["sha256"] == hashlib.sha256(data).hexdigest(), f"{name} SHA256 与清单不符"


def test_subset_coverage_matches_documented_fallback() -> None:
    """每个族不含的码位必须与文档化的系统兜底集合**完全一致**（多/少都算清单腐败）。"""
    manifest = _manifest()
    fonts = manifest["fonts"]
    for key, entry in fonts.items():
        missing = frozenset(entry["missing_codepoints"])
        extra = sorted(missing - DOCUMENTED_FALLBACK_CODEPOINTS)
        absent = sorted(DOCUMENTED_FALLBACK_CODEPOINTS - missing)
        assert missing == DOCUMENTED_FALLBACK_CODEPOINTS, (
            f"{key} 缺字集合与文档化的系统兜底集合不一致。\n"
            f"  清单多出（覆盖退化 / 新字符未入库）：{extra}\n"
            f"  清单少了（兜底说明过期）：{absent}"
        )
        assert all(
            info["covered"] == manifest["charset_size"] - len(missing)
            for info in entry["files"].values()
        )
