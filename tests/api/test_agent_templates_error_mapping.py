"""#177 Coverage-Gap 补测：直接调用 _run_service（不经 TestClient）。

coverage.py（7.15.2 + Python 3.13）在 pytest 环境下对 TestClient portal
线程内异常传播路径存在统计盲区——except 分支已执行但 coverage 不记录；
直接调用 router 模块 _run_service 可在 pytest 下正常记录。

补测非 TDD：被测源码已存在（agent_templates.py L105-110），本文件用例
直接通过，不改动任何 src/ 文件。
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.api
class TestRunServiceErrorMapping:
    """agent_templates._run_service 异常映射（404/409/422）直接调用契约。"""

    async def test_run_service_not_found_maps_404(self):
        """AgentTemplateNotFoundError → HTTPException 404（detail 含异常
        消息，agent_templates.py L105-106）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import _run_service
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateNotFoundError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateNotFoundError("x")))
        assert ei.value.status_code == 404
        assert "x" in ei.value.detail

    async def test_run_service_builtin_maps_409(self):
        """AgentTemplateBuiltinError → HTTPException 409（detail 精确等于
        DEFAULT_DELETE_DETAIL，agent_templates.py L107-108）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import (
            DEFAULT_DELETE_DETAIL,
            _run_service,
        )
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateBuiltinError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateBuiltinError("x")))
        assert ei.value.status_code == 409
        assert ei.value.detail == DEFAULT_DELETE_DETAIL

    async def test_run_service_service_error_maps_422(self):
        """AgentTemplateServiceError → HTTPException 422（detail 含异常
        消息，agent_templates.py L109-110）。"""
        from fastapi import HTTPException

        from inkflow.api.routers.agent_templates import _run_service
        from inkflow.domain.ports.agent_template_errors import (
            AgentTemplateServiceError,
        )

        async def _raise(exc):
            raise exc

        with pytest.raises(HTTPException) as ei:
            await _run_service(_raise(AgentTemplateServiceError("x")))
        assert ei.value.status_code == 422
        assert "x" in ei.value.detail
