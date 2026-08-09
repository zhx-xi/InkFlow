"""F21 TXT 序列化器 — BookDocument → UTF-8 纯文本（spec §5.3）.

纯函数、零依赖、确定性：同一 BookDocument 两次调用输出逐字节相同
（无时间戳/随机量，§5.4/§9.2 场景 1）。

输出结构（每行后 \\n，spec §5.3/§6.2）:
1. 首行 = 书名；次行 = "=" 重复 30 个分隔线
2. 每个卷: 「第 {N} 卷 {title}」（title 为空 → 「第 {N} 卷」占位，无尾随
   空格）+ "-" 重复 30 个分隔线；每个章: 「第 {M} 章 {title}」+ 空行 +
   正文原样（含换行，不转义不清洗）
3. 未分组卷（title == "未分组"，service 聚合常量）: 不输出卷标题行与
   "-" 分隔线，直接输出其章（单卷退化，§5.3）
4. 附录（settings 非空）: 「附录：设定档案」+ 按 settings 顺序分节
   （service 聚合保证固定顺序 character → world → outline → timeline →
   foreshadowing；同一 type 只输出一次分节标题），每条目输出 name 行 +
   content 行；settings 为空 → 不输出附录
5. 空项目（无卷无章无设定）→ 书名 + 分隔线（§7 E4）

依据: specs/f21-export-service/spec.md §3.2/§5.3/§6.2/§7 E3-E4。
"""

from __future__ import annotations

from inkflow.domain.models.output import BookDocument

_UNGROUPED_TITLE = "未分组"
"""service 聚合常量（未分组卷标题；本模块据此折叠卷前缀，§5.3 单卷退化）。"""

_LINE_EQ = "=" * 30
"""书名分隔线（spec §3.2 示例: 30 个 =）。"""

_LINE_DASH = "-" * 30
"""卷分隔线（spec §3.2 示例: 30 个 -）。"""

_APPENDIX_TITLE = "附录：设定档案"
"""附录标题行（settings 非空时输出）。"""

_SECTION_TITLES = {
    "character": "【角色】",
    "world": "【世界观】",
    "outline": "【大纲】",
    "timeline": "【时间线】",
    "foreshadowing": "【伏笔】",
}
"""分节标题映射（spec §5.3 附录示例形态）。"""


def to_txt(book: BookDocument) -> str:
    """BookDocument → TXT 纯文本（行级结构见模块 docstring）.

    Args:
        book: 聚合层产出的统一中间表示.

    Returns:
        UTF-8 文本字符串（每行以 \\n 结尾）；同一输入两次调用结果逐字节相同.
    """
    lines: list[str] = [book.meta.title, _LINE_EQ]
    for vol_no, volume in enumerate(book.volumes, start=1):
        if volume.title != _UNGROUPED_TITLE:
            vol_line = f"第 {vol_no} 卷 {volume.title}" if volume.title else f"第 {vol_no} 卷"
            lines.extend(["", vol_line, _LINE_DASH])
        for ch_no, chapter in enumerate(volume.chapters, start=1):
            lines.extend(["", f"第 {ch_no} 章 {chapter.title}", "", chapter.content])
    if book.settings:
        lines.append("")
        lines.append(_APPENDIX_TITLE)
        seen_types: set[str] = set()
        for setting in book.settings:
            if setting.type not in seen_types:
                seen_types.add(setting.type)
                lines.extend(["", _SECTION_TITLES[setting.type]])
            lines.extend([setting.name, setting.content])
    return "\n".join(lines) + "\n"
