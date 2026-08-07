"""#177 Coverage-Gap 补测：直接调用 _run_service（不经 TestClient）。

coverage.py（7.15.2 + Python 3.13）在 pytest 环境下对 TestClient portal
线程内异常传播路径存在统计盲区——except 分支已执行但 coverage 不记录；
直接调用 router 模块 _run_service 可在 pytest 下正常记录。

补测非 TDD：被测源码已存在（provider_configs.py L71-74），本文件用例
直接通过，不改动任何 src/ 文件。
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.api
class TestRunServiceErrorMapping:
    """provider_configs._run_service 异常映射（422/404）直接调用契约。"""

    async def test_run_service_service_error_maps_422(self):
        """ProviderConfigServiceError → HTTPException 422（detail 含异常
        消息，provider_configs.py L71-72）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.provider_configs import _run_service
        from inkflow.domain.ports.provider_config_errors import (
            ProviderConfigServiceError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(ProviderConfigServiceError("x")))
        assert ei.value.status_code == 422
        assert "x" in ei.value.detail

    async def test_run_service_not_found_maps_404(self):
        """ProviderConfigNotFoundError → HTTPException 404（detail 含异常
        消息，provider_configs.py L73-74）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.provider_configs import _run_service
        from inkflow.domain.ports.provider_config_errors import (
            ProviderConfigNotFoundError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(ProviderConfigNotFoundError("x")))
        assert ei.value.status_code == 404
        assert "x" in ei.value.detail
