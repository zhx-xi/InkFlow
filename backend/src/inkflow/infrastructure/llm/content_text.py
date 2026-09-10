from __future__ import annotations


def _text_block_text(block: dict[str, object]) -> str:
    """Extract the text payload of a type=="text" content block.

    Prefers the "text" key, falls back to the "content" key (OpenAI-compatible
    shape); returns "" when both keys are absent. Non-str values are
    stringified.
    """
    value = block.get("text")
    if value is None:
        value = block.get("content")
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def content_text(content: object) -> str:
    """Normalize LLM content into plain text (#1045 unified semantics).

    str -> returned unchanged; dict with type=="text" -> its text payload; list
    -> bare str items plus type=="text" dicts joined in order (thinking blocks,
    ints, None, and other dicts are skipped); anything else (None, int, dict
    without type=="text") -> "".
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and content.get("type") == "text":
        return _text_block_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(_text_block_text(item))
        return "".join(parts)
    # Intentionally silent: unexpected shapes normalize to "" without logging (#1039 decision 3b).
    return ""
