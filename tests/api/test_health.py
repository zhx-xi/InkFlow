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

    def test_health_version_dynamic_from_inkflow_version(self, client):
        """契约（spec §2.4）：/health 的 version 必须动态读取 inkflow.__version__，
        而非硬编码字面量——patch 版本号后端点应返回被 patch 的值（现实现硬编码 → RED）。"""
        # Arrange：模拟发布构建注入的版本号
        with patch("inkflow.__version__", "9.9.9"):
            # Act：请求健康检查
            resp = client.get("/health")
        # Assert：version 应动态反映 inkflow.__version__，而非硬编码字面量
        assert resp.status_code == 200
        assert resp.json()["version"] == "9.9.9"

    def test_health_version_is_non_empty_string(self, client):
        """加固（spec §2.4）：/health 的 version 字段应存在且为非空字符串，
        避免打包分发后版本信息缺失或为空。"""
        # Arrange：无需额外准备
        # Act：请求健康检查
        resp = client.get("/health")
        # Assert：version 存在且为非空字符串
        assert resp.status_code == 200
        version = resp.json()["version"]
        assert isinstance(version, str)
        assert version.strip() != ""


class TestLifespan:
    def test_lifespan_startup_and_shutdown(self):
        """应用 lifespan：启动时执行 setup_logging + create_tables + seed
        内置 provider，健康检查可用"""
        fake_seed = AsyncMock()
        fake_svc = AsyncMock()
        fake_svc.seed_builtin_providers = fake_seed
        with patch("inkflow.api.app.setup_logging") as mock_setup_logging, patch(
            "inkflow.api.app.create_tables", new=AsyncMock()
        ) as mock_create_tables, patch(
            "inkflow.api.app.get_provider_config_service", return_value=fake_svc
        ) as mock_svc_factory, TestClient(app) as lifespan_client:
            resp = lifespan_client.get("/health")
            assert resp.status_code == 200
        mock_setup_logging.assert_called_once()
        mock_create_tables.assert_awaited_once()
        # #106 F1：lifespan 接线 seed（mock create_tables 后表不存在，seed 必须 mock 才可测）
        mock_svc_factory.assert_called_once()
        fake_seed.assert_awaited_once()
