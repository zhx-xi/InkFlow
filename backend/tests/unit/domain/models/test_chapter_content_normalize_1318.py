"""#1318 RED 契约 — 首行标题回声判据放宽为「章号 + 章名」双条件。

来源: issue #1318（v0.15.0-rc4 完整旅程实测：9 章正文中 **2 章**首行仍是标题行）

真实样本（rc4 隔离库实测，逐字）
----------------------------------
    章   chapters.title               content 首行
    3    第3章 旧宅旧事一桩            　　三章　旧宅旧事一桩
    8    第8章 接任理账柴米艰难        　　第8章 接任理账 柴米艰难

`drafts.content` 与 `chapters.content` 首行逐字相同 ⇒ 收口剥离**执行过但未命中**
（`draft_service.confirm` 调了 `strip_first_line_title_echo`，判据太严）。

根因（探针 A 实测，非推理）
----------------------------
`_is_title_echo_line`（chapter.py:338-360）→ `_is_title_equivalent`（:179-187）
→ `normalize_chapter_title`（:112-159）要求**归一后逐字相等**：

- ch3：正文「三章」**丢「第」** → `_ARABIC_PREFIX_RE`/`_CHINESE_PREFIX_RE`
  （`chapter.py:37-38`）都要求「第…章」→ 前缀不成立 → `normalize` 原样返回 → 不等
- ch8：正文**中间多一个空格** → `normalize_chapter_title` 只归一序号形态与
  **序号后**分隔符（`:142`），不动正文内部空格 → 不等

修复方向（已拍板 A'，见 issue 评论「方案审计」）
-------------------------------------------------
判据改「**章号 + 章名**」双条件：解析（可选）`第N章` 前缀得 (章号, 章名)，
要求 **章名去全部空白后逐字相等** 且 **章号相等或一侧缺省**。

🔴 明确**否决**的两条替代判据（issue 探针 C 实测，本文件以反向断言永久守护）：
- **纯形态判据**（A-2）：`第8章 接任理账 全书的第一处转折` 与章名不等也被删 →
  误删面过大（连 `十七八章回小说里，常有这样的桥段。` 都命中）
- **在 `chapter_service.update_chapter` 补第三个调用点**（A-3）：
  `chapter.py:350-358` 明文禁止收口判据进入通用守卫路径（否则推翻 #1112 ——
  用户手写首段恰与章名同文是**合法正文**）

契约
----
C1 命中放宽（判据过严的修复面）：
     - 「丢「第」」形态 `三章　<章名>` → 剥离
     - 「内部多空格」形态 `第8章 <章名带空格>` → 剥离
C2 误删面为零（**关键反向断言**）：
     - `第三章 <章名>，是他童年的全部记忆。` → **不剥离**（章名后缀不同）
     - `第8章 接任理账 全书的第一处转折` → **不剥离**（章名不等）
     - `十七八章回小说里，常有这样的桥段。` → **不剥离**（非标题行）
C3 收口路径边界不破：#1112 铁律 —— 顶格等价行不属回声（通用归一路径管）；
     通用归一/守卫仍视带缩进的标题等价行为**正文段落**，判据放宽**不得**外溢。
C4 幂等：剥离后再次调用恒等（`strip(strip(x)) == strip(x)`）。
C5 可证伪自证：把判据退回「归一后逐字相等」→ C1 两条必 FAIL
     （见 `TestC5Falsifiability`，以 monkeypatch 还原旧判据实现）。

基线: main @ ffd825b2
"""

from __future__ import annotations

import pytest

from inkflow.domain.models import chapter as chapter_module
from inkflow.domain.models.chapter import (
    normalize_chapter_title,
    strip_first_line_title_echo,
)

FW = "\u3000"

# 🔴 真实样本（rc4 隔离库逐字，issue #1318 表格）
TITLE_CH3 = "第3章 旧宅旧事一桩"
ECHO_CH3 = f"{FW}{FW}三章{FW}旧宅旧事一桩"

TITLE_CH8 = "第8章 接任理账柴米艰难"
ECHO_CH8 = f"{FW}{FW}第8章 接任理账 柴米艰难"

BODY = "第二段正文。"


def _strip(first_line: str, title: str) -> str:
    """把首行 + 正文装入完整正文后调收口剥离。"""
    return strip_first_line_title_echo(f"{first_line}\n\n{BODY}", title)


class TestC1HitWidened:
    """C1: 判据过严的两类真实形态必须命中（issue 主现象）。"""

    def test_ch3_missing_di_prefix_stripped(self) -> None:
        """🔴 主用例 ch3：正文「三章」丢「第」→ 剥离（rc4 实测未剥离）。"""
        out = _strip(ECHO_CH3, TITLE_CH3)
        assert out == BODY, f"ch3 形态未剥离（判据仍过严）: {out!r}"

    def test_ch8_inner_space_stripped(self) -> None:
        """🔴 主用例 ch8：正文章名内部多一个空格 → 剥离（rc4 实测未剥离）。"""
        out = _strip(ECHO_CH8, TITLE_CH8)
        assert out == BODY, f"ch8 形态未剥离（判据仍过严）: {out!r}"

    @pytest.mark.parametrize(
        ("name", "first_line", "title"),
        [
            ("半角缩进 ch3 形态", f"  {ECHO_CH3.strip()}", TITLE_CH3),
            ("全角单缩进 ch8 形态", f"{FW}{ECHO_CH8.strip()}", TITLE_CH8),
            ("ch3 多内部空格", f"{FW}{FW}三章{FW}旧宅{FW}旧事一桩", TITLE_CH3),
        ],
    )
    def test_echo_variants_stripped(self, name: str, first_line: str, title: str) -> None:
        """缩进宽度与内部空白数不改变命中（判据基于内容而非排版）。"""
        assert _strip(first_line, title) == BODY, f"{name}: 未剥离"


class TestC2NoFalsePositive:
    """C2: 误删面必须为零 —— 纯形态判据（A-2）被否决的直接理由。

    issue 探针 C 实测：纯形态判据下这三条**全部**被当标题首行删除。
    本类断言它们必须逐字节原样返回。放宽判据**不得**以「看起来像标题」为准，
    必须同时满足「章名（去全部空白）逐字相等」。
    """

    @pytest.mark.parametrize(
        ("name", "first_line", "title"),
        [
            (
                "章名后接正文（章名是前缀）",
                f"{FW}第三章 旧宅旧事一桩，是他童年的全部记忆。",
                TITLE_CH3,
            ),
            (
                "章名不等（纯形态判据会误删）",
                f"{FW}第8章 接任理账 全书的第一处转折",
                TITLE_CH8,
            ),
            (
                "散文里的章回（纯形态判据会误删）",
                f"{FW}十七八章回小说里，常有这样的桥段。",
                TITLE_CH3,
            ),
        ],
    )
    def test_prose_not_stripped(self, name: str, first_line: str, title: str) -> None:
        """🔴 关键反向断言：正文段落逐字节原样返回。"""
        content = f"{first_line}\n\n{BODY}"
        out = strip_first_line_title_echo(content, title)
        assert out == content, f"[{name}] 合法正文被误删（误删面不为零）: {out!r}"

    def test_chapter_number_mismatch_not_stripped(self) -> None:
        """章号不等且章名不等 → 不剥离。"""
        content = f"{FW}{FW}第99章 换了个完全不同的章名\n\n{BODY}"
        assert strip_first_line_title_echo(content, TITLE_CH3) == content

    def test_chapter_number_mismatch_name_equal_not_stripped(self) -> None:
        """章号不等但章名相等 → **不**剥离（双条件：章号须相等或一侧缺省）。

        🔴 这是「章号」条件的唯一实际约束面：两侧章号都能解析时必须相等。
        否则「第7章 <同一章名>」这种**跨章误写**会被当成本章回声删掉。
        """
        content = f"{FW}{FW}第7章 旧宅旧事一桩\n\n{BODY}"
        assert strip_first_line_title_echo(content, TITLE_CH3) == content


class TestC3BoundaryPreserved:
    """C3: 收口路径边界不破 —— 放宽不得外溢到通用归一/守卫（#1112 铁律）。"""

    def test_top_aligned_not_echo(self) -> None:
        """顶格等价行由通用归一路径处理，不属回声（既有契约）。"""
        content = f"{TITLE_CH3}\n\n{BODY}"
        assert strip_first_line_title_echo(content, TITLE_CH3) == content

    def test_chapter_content_needs_normalize_unchanged_for_indented_echo(self) -> None:
        """#1112：通用守卫仍视「带缩进的标题等价行」为**正文段落**。

        判据放宽后该行为必须逐字节不变（`needs_normalize` 对缩进等价行
        不计入「重复标题行」脏数据）。
        """
        # 该行形态（缩进 + 与 title 等价）在通用守卫眼里不是重复标题行
        from inkflow.domain.models.chapter import _is_duplicate_title_line

        assert _is_duplicate_title_line(f"{FW}{FW}{TITLE_CH3}", TITLE_CH3) is False
        assert _is_duplicate_title_line(ECHO_CH3, TITLE_CH3) is False

    def test_no_title_returns_unchanged(self) -> None:
        """空 title → 原样返回（收口无法判定回声）。"""
        content = f"{ECHO_CH3}\n\n{BODY}"
        assert strip_first_line_title_echo(content, "") == content

    def test_middle_echo_untouched(self) -> None:
        """只处理首行：正文中部同形段落保留。"""
        content = f"{BODY}\n\n{ECHO_CH3}"
        assert strip_first_line_title_echo(content, TITLE_CH3) == content


class TestC4Idempotent:
    """C4: 剥离幂等（不动点）。"""

    @pytest.mark.parametrize(
        ("first_line", "title"),
        [(ECHO_CH3, TITLE_CH3), (ECHO_CH8, TITLE_CH8)],
    )
    def test_strip_is_fixpoint(self, first_line: str, title: str) -> None:
        once = _strip(first_line, title)
        twice = strip_first_line_title_echo(once, title)
        assert once == twice == BODY, f"剥离非不动点: once={once!r} twice={twice!r}"

    def test_strip_is_fixpoint_on_rejected_line(self) -> None:
        """未命中（章号不等）的行必须幂等 —— 不收窄也不放大。"""
        content = f"{FW}{FW}第7章 旧宅旧事一桩\n\n{BODY}"
        once = strip_first_line_title_echo(content, TITLE_CH3)
        assert once == content
        assert strip_first_line_title_echo(once, TITLE_CH3) == once


class TestC5Falsifiability:
    """C5: 可证伪自证 —— 退回旧判据（归一后逐字相等）→ C1 必 FAIL。

    若本类在旧实现下也通过，说明 C1 的断言没有真正驱动修复（恒真）。
    """

    def test_legacy_judgement_fails_c1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """把 `_is_title_echo_line` 换成 #1261 的严格等价判据 → ch3/ch8 不剥离。"""

        def _legacy_echo_line(line: str, title: str) -> bool:
            stripped = line.strip()
            if not stripped:
                return False
            return normalize_chapter_title(stripped) == normalize_chapter_title(title)

        monkeypatch.setattr(chapter_module, "_is_title_echo_line", _legacy_echo_line)

        # 旧判据下这两条**必须**不剥离 —— 证明 C1 断言有区分度
        assert _strip(ECHO_CH3, TITLE_CH3) != BODY, "旧判据竟命中了 ch3：C1 断言无效（恒真）"
        assert _strip(ECHO_CH8, TITLE_CH8) != BODY, "旧判据竟命中了 ch8：C1 断言无效（恒真）"
