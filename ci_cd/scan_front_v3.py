r"""前端断言质量扫描 v4 — 按 test/it 块粒度判断断言强弱（#524 扫描器固化修复版）。

v4 相对 v3 的三处修复（2026-08-20 #524 审计实证，102 命中里 98 个实际有效）：
1. STRONG 正则容忍 expect 参数中的嵌套括号（`expect(useAgentStore.getState().config.x).toBe(...)`
   —— v3 的 `expect\([^)]*\)` 在 `getState()` 的 `)` 处截断，后续 `.toBe(...)` 匹配不到 STRONG，
   整块被误判为「只有弱断言」）。新正则以括号平衡方式匹配 `expect(...)` 全参数（支持多层嵌套）。
2. `toBe(具体值)` 不再一律计弱：`toBe('zhipu/glm-4.5')` / `toBe(8)` / `toBe(SENTINEL)` 是强断言
   （具体值/具名常量）；只有 `toBe(null|undefined|true|false)` 才计弱（存在性/布尔标志）。
3. `not.toHaveBeenCalled()` 否定路径是**有效守卫**（类型 4：未配置→不发请求、Escape 取消、
   空值静默等防副作用契约），不得计弱——从 WEAK 集合移除 `not\.` 前缀的调用断言。

强断言 matcher 集合（修改逻辑后这些都会变）：
  toEqual / toStrictEqual / toContain / toHaveTextContent / toHaveValue /
  toHaveProperty / toBeDisabled / toBeEnabled / toHaveLength / toBeInTheDocument /
  toMatchObject / toHaveAttribute / toBeChecked / toBeVisible / toHaveClass /
  toContainEqual / toHaveFocus / toBeCloseTo / toBeGreaterThan / toBeLessThan /
  toHaveBeenCalledWith / toHaveBeenNthCalledWith / toHaveBeenLastCalledWith /
  toHaveDisplayValue / toHaveAccessibleName / toHaveDescription /
  toBe(字面量/具名常量)   ← v4 新增

弱断言：toBeTruthy / toBeFalsy / toBeDefined / toBeUndefined / toBeNull /
  toBe(null|undefined|true|false) / toHaveBeenCalled / toHaveBeenCalledTimes（无参数）
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

# 仓库根 = 本脚本所在仓库的根（ci_cd/.. 或 frontend 扫描目标的共同祖先）；亦可显式覆盖
ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIRS = (
    [
        Path.cwd() / "frontend" / "packages" / "renderer" / "src",
        Path.cwd() / "frontend" / "packages" / "electron" / "src",
    ]
    if (Path.cwd() / "frontend").exists()
    else [
        ROOT / "frontend" / "packages" / "renderer" / "src",
        ROOT / "frontend" / "packages" / "electron" / "src",
    ]
)
FRONTEND_DIRS = [d for d in FRONTEND_DIRS if d.exists()]


def _paren_balanced(name: str) -> str:
    """构造可匹配 expect(...) 全参数的括号平衡正则片段（支持多层嵌套）。"""
    # 一层：任何非括号字符 或 一对括号（可含一层括号）
    inner = r"(?:[^()]|\((?:[^()]|\([^()]*\))*\))*"
    return rf"{name}\({inner}\)"


EXPECT = _paren_balanced("expect")
NOT = r"(?:\.not\.)?"

_STRONG_MATCHERS = (
    "toEqual|toStrictEqual|toContain|toContainEqual|toHaveTextContent|toHaveValue|"
    "toHaveProperty|toHaveLength|toBeDisabled|toBeEnabled|toMatchObject|toHaveAttribute|"
    "toBeChecked|toBeVisible|toHaveClass|toHaveFocus|toBeCloseTo|toBeGreaterThan|"
    "toBeLessThan|toHaveBeenCalledWith|toHaveBeenNthCalledWith|toHaveBeenLastCalledWith|"
    "toHaveDisplayValue|toHaveAccessibleName|toHaveDescription|toBeInTheDocument|"
    r"toHaveBeenCalledTimes\(-?\d+\)"
)

STRONG = re.compile(
    rf"{EXPECT}\.{NOT}(?:{_STRONG_MATCHERS}|"
    rf"toBe\((?:'(?:[^']|\\')*'|\"(?:[^\"]|\\\")*\"|(?!null|undefined|true|false)[A-Za-z_][A-Za-z0-9_.-]*|-?\d)"
    rf"|toBe\((?!null|undefined|true|false\))[^()]*\))"
)
# toBe(具体值/表达式)：字符串字面量 / 非布尔/非空具名常量（SENTINEL 等）/ 数字 /
# 一般表达式（BASE+'/health'、before+1）→ 强；null/undefined/true/false 字面量 → 弱
# （存在性/布尔标志，不能区分行为）。
WEAK = re.compile(
    rf"{EXPECT}\.{NOT}(?:toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|"
    rf"toBe\((?:null|undefined|true|false)\)|toHaveBeenCalled(?!With|Times)"
    rf"|toHaveBeenCalledTimes\(\))"
)
# 守卫（类型 4）：not.toHaveBeenCalled() 否定路径 = 有效守卫，不计弱（v4 从 WEAK 拆出）
GUARD = re.compile(rf"{EXPECT}\.not\.(?:toHaveBeenCalled|toHaveBeenCalledTimes)\(\)")


def split_blocks(src: str):
    """按 describe/it/test 块切分（近似：花括号平衡）。"""
    _blocks_re = re.compile(
        r"\b(it|test)\s*\((['\"])(.*?)\2\s*,\s*(?:async\s*)?"
        r"(?:\(\)\s*=>|function\s*\()"
    )
    blocks = []
    for m in _blocks_re.finditer(src):
        start = m.end()
        depth = 0
        i = src.find("{", start)
        if i == -1:
            continue
        depth = 1
        j = i + 1
        while j < len(src) and depth > 0:
            c = src[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        name = m.group(3)
        body = src[i:j]
        blocks.append((m.start(), name, body, i))
    return blocks


def main() -> None:
    counter = Counter()
    weak_only_blocks: list[
        tuple[str, str, str]
    ] = []  # (file, test_name, weak_matchers)
    guard_blocks: list[tuple[str, str, str]] = []
    strong_blocks: list[tuple[str, str, str]] = []
    by_file: Counter = Counter()
    for d in FRONTEND_DIRS:
        for ts in sorted(d.rglob("*.test.*")):
            if "node_modules" in str(ts):
                continue
            src = ts.read_text(encoding="utf-8", errors="replace")
            rel = str(ts).replace(str(ROOT), "")
            for pos, name, body, _ in split_blocks(src):
                del pos  # start offset 仅块切分用，判定不依赖
                strong_m = STRONG.findall(body)
                guard_m = GUARD.findall(body)
                weak_m = WEAK.findall(body)
                if strong_m:
                    strong_blocks.append(
                        (rel, name, ", ".join(str(m) for m in strong_m[:3]))
                    )
                    continue
                if guard_m:
                    # 仅守卫 + 无强断言：有效（类型 4），单列不计弱
                    guard_blocks.append(
                        (rel, name, ", ".join(str(m) for m in guard_m[:3]))
                    )
                    continue
                if weak_m:
                    counter["weak-only-block"] += 1
                    by_file[ts.name] += 1
                    weak_only_blocks.append(
                        (rel, name, ", ".join(str(m) for m in weak_m[:4]))
                    )
    print(f"=== 弱断言候选块（无强断言、无守卫）：{counter['weak-only-block']} ===")
    print(
        "=== 守卫块（not.toHaveBeenCalled 否定路径，类型 4 有效，不计弱）："
        f"{len(guard_blocks)} ==="
    )
    print("\n=== 按文件分布（弱候选）===")
    for f, v in by_file.most_common():
        print(f"{v:4d}  {f}")
    print("\n=== 弱候选明细（前120）===")
    for rel, name, wm in weak_only_blocks[:120]:
        print(f"{rel}")
        print(f"    | {name[:90]}")
        print(f"    | weak: {wm}")
    print("\n=== 守卫块清单（前40）===")
    for rel, name, gm in guard_blocks[:40]:
        print(f"{rel}")
        print(f"    | {name[:90]}")
        print(f"    | guard: {gm}")


if __name__ == "__main__":
    main()
