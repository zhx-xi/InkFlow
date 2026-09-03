"""i18n REST API — 本地化消息目录（F57 #888-S1 / spec §3.1）。"""

from __future__ import annotations

from fastapi import APIRouter

from inkflow.i18n.resolver import load_messages, resolve_locale
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1/i18n", tags=["I18n"])


@router.get("/messages")
@instrument(caller_type="api")
async def get_messages(lng: str | None = None) -> dict:
    """按 lng 返回 messages 域本地化目录（msgid→template）。
    lng 缺省 resolve_locale(None)（zh 默认）；F7 信封 {ok, data}；不支持回退 zh。"""
    locale = resolve_locale(lng)
    return {"ok": True, "data": load_messages("messages", locale)}
