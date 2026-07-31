"""基础测试 - 验证项目骨架。"""

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
