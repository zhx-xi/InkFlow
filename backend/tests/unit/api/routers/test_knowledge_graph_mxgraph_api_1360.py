"""#1360 drawio 导入/导出 API 契约测试（M9；只写测试，不改 src/）.

被测 router: inkflow.api.routers.knowledge_graph（追加 2 端点，spec §3.1/§5.7）。

【RED 预期】端点未实现 → 现返回 404 → 本文件用例 FAIL（收集期不报错，比缺模块 RED 更细粒度）。

【GREEN 必须匹配的契约】
1) GET /api/v1/projects/{project_id}/knowledge-graph/export?format=mxgraph
   - format: Literal["mxgraph"] = "mxgraph"（其它值 → FastAPI 422，service 零调用）
   - 调用 inkflow.api.routers.knowledge_graph._get_svc(db) → svc.export_mxgraph(pid)
     → (xml: str, filename: str)
   - 200；Content-Type 前缀 application/xml；Content-Disposition 含 attachment 与
     「filename*=UTF-8''<URL 编码文件名>」（镜像 F21 export 头部形态）
   - body 为 xml 原文（UTF-8）
   - ProjectNotFoundError → 404；非法 UUID → 404「项目不存在」（不经 service）
2) POST /api/v1/projects/{project_id}/knowledge-graph/import?mode=merge|replace
   - mode: Literal["merge","replace"] = "merge"（缺省 merge；其它值 → 422）
   - 请求体 = 原始 XML 字节（Content-Type application/xml；**非 JSON**）
   - 调用 svc.import_mxgraph(pid, xml_text, mode=<mode>)
   - 200 → KnowledgeGraphImportResult.model_dump(mode="json")
     {mode,total,imported,skipped,failed,deleted,details}
   - MxGraphImportError（422 基类子类）→ 422，detail = str(e)
   - 非 UTF-8 请求体 → 422（detail 含「非法 mxGraph XML」），**不 500**
   - ProjectNotFoundError → 404

依据: specs/f48-knowledge-graph/spec.md §3.1/§3.2/§3.3/§5.7/§7 边界 18-25/§13 M9。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.knowledge_graph import (
    KnowledgeGraphImportIssue,
    KnowledgeGraphImportResult,
)
from inkflow.domain.ports.knowledge_graph_errors import (
    KnowledgeGraphServiceError,
    MxGraphImportError,
)
from inkflow.domain.ports.world_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
PID_STR = str(PID)

SAMPLE_XML = (
    '<mxfile host="InkFlow" type="device"><diagram id="inkflow-knowledge-graph" name="知识图谱">'
    '<mxGraphModel dx="800" dy="600"><root><mxCell id="0" /><mxCell id="1" parent="0" />'
    "</root></mxGraphModel></diagram></mxfile>"
)

XML_HEADERS = {"Content-Type": "application/xml"}


def _mock_svc() -> MagicMock:
    svc = MagicMock()
    svc.export_mxgraph = AsyncMock(return_value=(SAMPLE_XML, "项目甲-knowledge-graph.drawio"))
    svc.import_mxgraph = AsyncMock(
        return_value=KnowledgeGraphImportResult(
            mode="merge",
            total=2,
            imported=1,
            skipped=1,
            failed=0,
            details=[
                KnowledgeGraphImportIssue(
                    kind="skipped",
                    edge_id="kr:1",
                    label="师承",
                    reason="该关系已存在（同键唯一）",
                )
            ],
        )
    )
    return svc


@pytest.fixture
def svc() -> MagicMock:
    mock = _mock_svc()
    with patch(
        "inkflow.api.routers.knowledge_graph.get_knowledge_graph_service", return_value=mock
    ):
        yield mock


EXPORT_URL = f"/api/v1/projects/{PID_STR}/knowledge-graph/export"
IMPORT_URL = f"/api/v1/projects/{PID_STR}/knowledge-graph/import"


class TestExportMxgraphEndpoint:
    """GET …/knowledge-graph/export。"""

    def test_export_returns_xml_attachment_with_filename(self, svc) -> None:
        resp = client.get(EXPORT_URL, params={"format": "mxgraph"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        disposition = resp.headers["content-disposition"]
        assert "attachment" in disposition
        assert "filename*=UTF-8''" in disposition
        assert resp.text == SAMPLE_XML
        svc.export_mxgraph.assert_awaited_once_with(PID)

    def test_export_default_format_is_mxgraph(self, svc) -> None:
        resp = client.get(EXPORT_URL)
        assert resp.status_code == 200
        svc.export_mxgraph.assert_awaited_once_with(PID)

    def test_export_invalid_format_short_circuits_422(self, svc) -> None:
        resp = client.get(EXPORT_URL, params={"format": "dot"})
        assert resp.status_code == 422
        svc.export_mxgraph.assert_not_awaited()

    def test_export_invalid_project_id_404_without_service(self, svc) -> None:
        resp = client.get("/api/v1/projects/not-a-uuid/knowledge-graph/export")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"
        svc.export_mxgraph.assert_not_awaited()

    def test_export_missing_project_404(self, svc) -> None:
        svc.export_mxgraph = AsyncMock(side_effect=ProjectNotFoundError())
        resp = client.get(EXPORT_URL)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"


class TestImportMxgraphEndpoint:
    """POST …/knowledge-graph/import。"""

    def test_import_merge_returns_counts(self, svc) -> None:
        resp = client.post(
            IMPORT_URL,
            params={"mode": "merge"},
            content=SAMPLE_XML.encode("utf-8"),
            headers=XML_HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "merge"
        assert set(body) == {"mode", "total", "imported", "skipped", "failed", "deleted", "details"}
        assert body["total"] == body["imported"] + body["skipped"] + body["failed"]
        assert body["details"][0]["kind"] == "skipped"
        svc.import_mxgraph.assert_awaited_once_with(PID, SAMPLE_XML, mode="merge")

    def test_import_default_mode_is_merge(self, svc) -> None:
        resp = client.post(IMPORT_URL, content=SAMPLE_XML.encode("utf-8"), headers=XML_HEADERS)
        assert resp.status_code == 200
        assert svc.import_mxgraph.await_args.kwargs["mode"] == "merge"

    def test_import_replace_mode_passed_through(self, svc) -> None:
        resp = client.post(
            IMPORT_URL,
            params={"mode": "replace"},
            content=SAMPLE_XML.encode("utf-8"),
            headers=XML_HEADERS,
        )
        assert resp.status_code == 200
        assert svc.import_mxgraph.await_args.kwargs["mode"] == "replace"

    def test_import_invalid_mode_422_without_service(self, svc) -> None:
        resp = client.post(
            IMPORT_URL,
            params={"mode": "overwrite"},
            content=SAMPLE_XML.encode("utf-8"),
            headers=XML_HEADERS,
        )
        assert resp.status_code == 422
        svc.import_mxgraph.assert_not_awaited()

    def test_import_invalid_xml_422_error_shape(self, svc) -> None:
        svc.import_mxgraph = AsyncMock(
            side_effect=MxGraphImportError("非法 mxGraph XML：根元素不是 mxfile")
        )
        resp = client.post(IMPORT_URL, content=b"<mxfile><diagram></mxfile>", headers=XML_HEADERS)
        assert resp.status_code == 422
        assert resp.json()["detail"] == "非法 mxGraph XML：根元素不是 mxfile"

    def test_import_non_utf8_body_422_not_500(self, svc) -> None:
        resp = client.post(IMPORT_URL, content=b"\xff\xfe<\x00m\x00", headers=XML_HEADERS)
        assert resp.status_code == 422
        assert "非法 mxGraph XML" in resp.json()["detail"]
        svc.import_mxgraph.assert_not_awaited()

    def test_import_missing_project_404(self, svc) -> None:
        svc.import_mxgraph = AsyncMock(side_effect=ProjectNotFoundError())
        resp = client.post(IMPORT_URL, content=SAMPLE_XML.encode("utf-8"), headers=XML_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"

    def test_import_error_is_422_subclass(self) -> None:
        assert issubclass(MxGraphImportError, KnowledgeGraphServiceError)
