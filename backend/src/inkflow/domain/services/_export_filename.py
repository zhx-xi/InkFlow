"""F21 导出文件名建议 — Windows 非法字符清洗与空书名占位（spec §7 E5/E7）.

纯函数，零依赖：清洗顺序 = strip → 空判（untitled 占位）→ 禁符替换 →
前 60 字符截断 → 拼接 "{书名}-{fmt.value}.txt"（spec §5.3/§7 E5）。

依据: specs/f21-export/spec.md §5.3/§7 E5-E7。
"""

from __future__ import annotations

from inkflow.domain.models.output import ExportFormat

_WINDOWS_FORBIDDEN_CHARS = '\\/:*?"<>|'
"""Windows 文件名禁符（spec §7 E5: \\ / : * ? " < > | 逐一替换为 "_"）。"""

_MAX_TITLE_CHARS = 60
"""文件名内书名截断上限（spec §7 E5: 清洗后取前 60 字符）。"""

_UNTITLED_PLACEHOLDER = "untitled"
"""空书名占位（spec §7 E7）。"""


def suggest_filename(title: str, fmt: ExportFormat) -> str:
    """建议导出文件名 — "{清洗后书名}-{fmt.value}.txt".

    Args:
        title: 项目书名（可含首尾空白与 Windows 非法字符）.
        fmt: 导出格式（v1.1 唯一 TXT）.

    Returns:
        建议文件名：strip 后为空 → "untitled-{fmt.value}.txt"（E7）；
        Windows 禁符逐一替换为 "_"（E5），再截断前 60 字符（E5 超长
        截断），最后拼接 "{书名}-{fmt.value}.txt"。
    """
    cleaned = title.strip()
    if not cleaned:
        return f"{_UNTITLED_PLACEHOLDER}-{fmt.value}.txt"
    for char in _WINDOWS_FORBIDDEN_CHARS:
        cleaned = cleaned.replace(char, "_")
    cleaned = cleaned[:_MAX_TITLE_CHARS]
    return f"{cleaned}-{fmt.value}.txt"
