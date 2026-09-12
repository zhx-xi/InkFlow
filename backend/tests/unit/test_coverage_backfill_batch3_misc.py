"""Batch 3 coverage backfill: deterministic domain helpers and infra edges."""

from __future__ import annotations

import importlib
import json
import locale
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest

from inkflow.domain.models.chapter import normalize_chapter_title
from inkflow.domain.services._chunking import ChunkingMode, chunk_text
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient
from inkflow.infrastructure.kernel import bootstrap as bootstrap_mod


def test_chunk_dialogue_skips_empty_trailing_block() -> None:
    """Public dialogue chunking omits an empty merged block."""
    chunks = chunk_text("\u201chi\u201d\n", mode=ChunkingMode.DIALOGUE, chunk_size=10)

    assert [chunk.text for chunk in chunks] == ["\u201chi\u201d"]


def test_paragraph_chunking_skips_empty_paragraph() -> None:
    """Public paragraph chunking skips empty paragraphs between separators."""
    chunks = chunk_text("a\n\n\n\nb", mode=ChunkingMode.PARAGRAPH, chunk_size=10)

    assert [chunk.text for chunk in chunks] == ["a", "b"]


def test_llm_chunking_filters_invalid_boundaries() -> None:
    """Public LLM chunking ignores invalid, out-of-range, and non-increasing boundaries."""
    chunks = chunk_text(
        "abcdef",
        mode=ChunkingMode.LLM,
        analyzer=lambda _text: [True, "x", 0, 6, 3, 3, 4],
    )

    assert [chunk.text for chunk in chunks] == ["abc", "d", "ef"]
    assert [chunk.start_offset for chunk in chunks] == [0, 3, 4]


def test_normalize_chapter_title_supports_thousand_prefix() -> None:
    """Public title normalization parses Chinese thousands and emits arabic format."""
    assert normalize_chapter_title("\u7b2c\u4e00\u5343\u96f6\u4e00\u7ae0 \u6807\u9898") == (
        "\u7b2c1001\u7ae0 \u6807\u9898"
    )


def test_resolve_locale_reads_lang_environment(monkeypatch) -> None:
    """Public locale resolution uses LANG when config language is empty."""
    resolver = importlib.import_module("inkflow.i18n.resolver")
    config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(config_mod.config, "lang", "")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    assert resolver.resolve_locale(None) == "en"


def test_resolve_locale_handles_locale_lookup_failure(monkeypatch) -> None:
    """Public locale resolution defaults to zh when OS lookup raises."""
    resolver = importlib.import_module("inkflow.i18n.resolver")
    config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(config_mod.config, "lang", "")
    monkeypatch.delenv("LANG", raising=False)

    def _raise() -> tuple[str, str]:
        raise RuntimeError("locale unavailable")

    monkeypatch.setattr(locale, "getlocale", _raise)

    assert resolver.resolve_locale(None) == "zh"


@pytest.mark.asyncio
async def test_ensure_kernel_frozen_mcp_without_sibling_uses_self(
    tmp_path: Path, monkeypatch
) -> None:
    """Public kernel bootstrap handles frozen MCP launches with no sibling kernel."""
    import inkflow

    state_file = tmp_path / "kernel.json"
    mcp_exe = tmp_path / "inkflow-mcp.exe"
    mcp_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(mcp_exe))
    monkeypatch.setattr(sys, "platform", "linux")

    class FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.pid = 4321
            state_file.write_text(
                json.dumps(
                    {
                        "port": 1234,
                        "token": "token",
                        "pid": self.pid,
                        "version": inkflow.__version__,
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(bootstrap_mod.subprocess, "Popen", FakePopen)

    handle = await bootstrap_mod.ensure_kernel(
        state_file=state_file,
        timeout=1.0,
        health_timeout=0.01,
    )

    assert handle.port == 1234
    assert handle.token == "token"
    assert handle.reused is False


@pytest.mark.asyncio
async def test_http_client_forwards_get_raw_and_stream_timeouts(monkeypatch) -> None:
    """Public get_raw and stream_sse forward per-request timeouts."""
    http_client_mod = importlib.import_module("inkflow.infrastructure.http.client")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {}

        async def aiter_lines(self):
            yield 'data: {"ok": true}'

    class FakeStream:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, *args) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            captured["constructor_timeout"] = kwargs["timeout"]

        async def request(self, method, path, **kwargs) -> httpx.Response:
            captured["get_raw_timeout"] = kwargs.get("timeout")
            return httpx.Response(
                200,
                text="raw",
                request=httpx.Request(method, f"http://test{path}"),
            )

        def stream(self, method, path, **kwargs) -> FakeStream:
            captured["stream_timeout"] = kwargs.get("timeout")
            return FakeStream()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(http_client_mod.httpx, "AsyncClient", FakeAsyncClient)
    client = InkFlowHTTPClient(SimpleNamespace(port=1, token="t"))

    raw = await client.get_raw("/export", timeout=7.5)
    frames = [frame async for frame in client.stream_sse("/stream", json={}, timeout=8.5)]

    assert raw == "raw"
    assert frames == [{"ok": True}]
    assert captured["get_raw_timeout"] == 7.5
    assert captured["stream_timeout"] == 8.5


@pytest.mark.asyncio
async def test_http_client_stream_outer_timeout_maps_to_timeout_error(monkeypatch) -> None:
    """Public stream_sse maps transport timeout raised before streaming."""
    http_client_mod = importlib.import_module("inkflow.infrastructure.http.client")

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        def stream(self, method, path, **kwargs):
            raise httpx.ReadTimeout("stream open timed out")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(http_client_mod.httpx, "AsyncClient", FakeAsyncClient)
    client = InkFlowHTTPClient(SimpleNamespace(port=1, token="t"))

    with pytest.raises(HttpApiError) as exc_info:
        [frame async for frame in client.stream_sse("/stream", json={}, timeout=1.25)]

    assert exc_info.value.status_code == 0
    assert exc_info.value.code == "TIMEOUT"
    assert "1.25" in exc_info.value.detail
