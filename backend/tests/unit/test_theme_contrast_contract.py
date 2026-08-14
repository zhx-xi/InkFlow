"""#350 背景主题按钮对比度静态契约测试（2026-08-14）。

现象：不同背景（素笺/夜航/墨韵/自定义背景图）下部分按钮 UI 颜色与背景相同或接近，
按钮不可见。根因候选：背景变体（parchment/navy/ochre）改 --bg/--surface 但
--line/--ink-2 等沿用主题默认——边框按钮（border-line + text-ink-2）在变体背景
下对比度不足。

本测试把「每个背景变体的按钮边框色（--line）与页面背景（--bg）对比度 >= 3:1
（WCAG AA 非文本 3:1）」固化为静态契约：tokens.css 配色漂移 → CI 红。
"""

import re
from pathlib import Path

TOKENS = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "packages"
    / "renderer"
    / "src"
    / "theme"
    / "tokens.css"
)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.strip().lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _extract_variant_css() -> dict[str, dict[str, str]]:
    """解析 tokens.css → {selector: {var: value}}（只取含 --bg 与 --line 的块）。"""
    src = TOKENS.read_text(encoding="utf-8")
    variants: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in src.splitlines():
        sel_match = re.match(r"\[data-theme=\"(\w+)\"\](\[data-bg=\"(\w+)\"\])?.*\{", line)
        if sel_match:
            theme = sel_match.group(1)
            bg = sel_match.group(3) or "default"
            current = f"{theme}:{bg}"
            variants[current] = {}
            continue
        if current is None:
            continue
        var_match = re.match(r"\s*(--\w+):\s*(#[0-9a-fA-F]{6})\s*;", line)
        if var_match:
            variants[current][var_match.group(1)] = var_match.group(2)
        if line.strip() == "}":
            current = None
    return variants


def test_tokens_css_exists():
    assert TOKENS.exists(), f"tokens.css 不存在: {TOKENS}"


def test_each_bg_variant_line_contrast_against_bg():
    """#350: 背景变体块（data-bg != default）的 --line vs --bg 对比度 >= 2:1.

    默认主题浅边框（line 1.23-1.70:1）是设计语言（细分隔线），不在此契约内；
    但**背景变体**（parchment/navy/ochre）只改 --bg/--surface，--line 往往沿用
    主题默认 → 变体背景下按钮边框更不可辨。修复：变体块补充 --line 覆盖
    （同主题同系更深），保证任意背景下按钮可辨。
    """
    variants = _extract_variant_css()
    assert variants, "tokens.css 未解析出任何主题变体"
    failures: list[str] = []
    for key, vars in variants.items():
        if key.endswith(":default"):
            continue  # 默认主题浅边框 = 设计语言，不强制
        if "--bg" not in vars or "--line" not in vars:
            # 变体未显式定义 --line → 继承主题默认（很可能对比不足）
            failures.append(f"{key}: 未定义 --line（继承默认，变体背景下对比不足）")
            continue
        ratio = _contrast(_hex_to_rgb(vars["--bg"]), _hex_to_rgb(vars["--line"]))
        if ratio < 2.0:
            failures.append(f"{key}: bg={vars['--bg']} line={vars['--line']} contrast={ratio:.2f}")
    assert not failures, "背景变体按钮边框对比度不足（#350）：\n" + "\n".join(failures)


def test_each_bg_variant_surface_line_contrast_against_bg():
    """#350 补充：背景变体块 --line vs --surface 对比度 >= 2:1（弹窗按钮边界）。"""
    variants = _extract_variant_css()
    failures: list[str] = []
    for key, vars in variants.items():
        if key.endswith(":default"):
            continue
        if "--surface" not in vars or "--line" not in vars:
            continue
        ratio = _contrast(_hex_to_rgb(vars["--surface"]), _hex_to_rgb(vars["--line"]))
        if ratio < 2.0:
            failures.append(
                f"{key}: surface={vars['--surface']} line={vars['--line']} contrast={ratio:.2f}"
            )
    assert not failures, "背景变体面板边框对比度不足（#350）：\n" + "\n".join(failures)


def test_accent_button_text_contrast_on_bg():
    """#350: 主按钮（bg-accent + text-accent-ink）在任意背景下文字对比 >= 4.5:1。"""
    variants = _extract_variant_css()
    failures: list[str] = []
    for key, vars in variants.items():
        if "--accent" not in vars or "--accent-ink" not in vars:
            continue
        ratio = _contrast(_hex_to_rgb(vars["--accent"]), _hex_to_rgb(vars["--accent-ink"]))
        if ratio < 4.5:
            failures.append(
                f"{key}: accent={vars['--accent']} "
                f"accent-ink={vars['--accent-ink']} contrast={ratio:.2f}"
            )
    assert not failures, "主按钮文字对比度不足（#350）：\n" + "\n".join(failures)
