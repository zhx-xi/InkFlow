"""基础测试 - 验证项目骨架。"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        """健康检查端点应返回 status=ok"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_response_time(self, client):
        """健康检查响应应快于 100ms"""
        import time

        start = time.time()
        client.get("/health")
        elapsed = time.time() - start
        assert elapsed < 0.1, f"Health check too slow: {elapsed:.3f}s"


class TestLifespan:
    def test_lifespan_startup_and_shutdown(self):
        """应用 lifespan：启动时执行 setup_logging + create_tables，健康检查可用"""
        with patch("inkflow.api.app.setup_logging") as mock_setup_logging, patch(
            "inkflow.api.app.create_tables", new=AsyncMock()
        ) as mock_create_tables, TestClient(app) as lifespan_client:
            resp = lifespan_client.get("/health")
            assert resp.status_code == 200
        mock_setup_logging.assert_called_once()
        mock_create_tables.assert_awaited_once()
