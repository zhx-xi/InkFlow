"""单元测试 fixture — 最小化，不提供数据库。

后端单元测试：纯函数、Mock、Pydantic DTO — 零 I/O。
"""

import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """session-scoped event loop for async unit tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_keys_dir():
    """临时密钥存储目录，测试后自动清理。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
