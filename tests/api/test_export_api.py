"""#53 F21 导出服务 — GET /api/v1/projects/{project_id}/export API 测试契约（TDD RED 阶段）。

本文件为 `api/routers/export.py`（NEW，specs/f21-export/spec.md v1.1 §3
API 契约 / §7 边界 / §9 测试策略 / §13 验收 M7）定义测试契约，覆盖 1 个下载端点：

- `GET /api/v1/projects/{project_id}/export` — 导出项目 TXT（query: format 可选
  仅 txt 缺省 txt、include_settings 可选默认 false）

权威来源：specs/f21-export/spec.md §3.1（端点总览）/ §3.2（请求响应
示例）/ §3.3（异常映射表）/ §7 E1-E11（边界）/ §9.1（API 层测试）/ §13 M7（验收）；
F19 token 中间件契约（spec §11 依赖，test_token_auth.py 同款）；F15 audit router
先例（_parse_id/_get_svc/_run_service 错误映射，backend/src/inkflow/api/routers/
audit.py）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app），验证纯 HTTP 行为；export 路由为新增模块
   `inkflow.api.routers.export`，本文件模块级 import 它（RED 阶段该
   模块不存在 → 收集期 ModuleNotFoundError，即预期失败形态，见文末
   RED 预期段）。

2. 【无 token 模式——硬性契约】本文件全部用例依赖 env
   `INKFLOW_SERVER_TOKEN` 未设置时中间件直通（test_token_auth.py 设计
   假设 #6 同款）：client fixture 内显式 monkeypatch.delenv，免疫开发者
   本机 shell 的 env 残留导致假失败。

3. 【模块契约】`inkflow.api.routers.export` 必须暴露（本文件 patch
   目标 = 最终契约，GREEN 必须匹配；镜像 F15 audit.py 结构）：
   - `router = APIRouter(prefix="/api/v1", tags=["导出"])` + 路由
     `GET /projects/{project_id}/export`（app.py 需
     `app.include_router(export.router)`）
   - `_parse_id(project_id: str) -> uuid.UUID`：支持 UUID 格式与 int 格式
     两种解析（audit.py 同款）；解析失败 → HTTPException(404,
     detail="项目不存在")，不进入服务层
   - `_get_svc(db: AsyncSession) -> ExportService`：模块级服务工厂，
     内部调用 deps.get_export_service(db)（deps.py 需新增该装配函数，
     镜像 deps.get_audit_service）
   - `_run_service(coro) -> Any`：统一异常映射（audit.py 同款）——
     ProjectNotFoundError → 404 detail=str(e)；其余 Exception → 500
     detail=f"内部错误: {e}"（ADR-012 风格，透传）

4. 【ExportService 契约】`async def export(project_id, include_settings:
   bool = False) -> BookDocument`：include_settings 由 router 从 query
   参数透传（缺省 false）；project_id 为 _parse_id 解析后的 uuid.UUID。
   测试通过 mock 断言 include_settings 值到达 service（位置/关键字传参
   形态自由，断言不锁形态）。

5. 【models.output 契约】`inkflow.domain.models.output` 必须导出
   BookDocument / BookMeta / BookVolume / BookChapter / BookSetting /
   ExportFormat（spec §2.2）。BookMeta 必填字段：title / genre /
   language / target_words / updated_at(datetime)；BookChapter 必填：
   title / content / order_index / word_count；BookVolume 必填：
   title / order_index / chapters；BookDocument 必填：meta / volumes /
   settings。本文件在用例体内【惰性 import】该模块（_make_book helper）：
   RED 阶段 models.output 与 export router 均不存在，顶部 import 二者
   时收集期只报告首个缺失模块；惰性化使 RED 报告干净地聚焦于
   `inkflow.api.routers.export` 单一缺失（GREEN 阶段两模块落地后正常
   解析，无行为差异）。

6. 【响应契约（spec §3.1/§3.2）】200 时：
   - Content-Type 含 `text/plain` 且 `charset=utf-8`
   - Content-Disposition 含 `attachment` 且文件名 = `{书名}-txt.txt`
     （URL 编码，防中文/空格破坏头——断言 urllib.parse.quote 编码后的
     文件名出现在头值中；GREEN 可用 filename* 或引号内百分号编码，
     均满足）
   - 响应体 = TXT 序列化文本，书名（book.meta.title）出现在文本中
   - 实现形态：FastAPI Response（字节内存组装，非 StreamingResponse，
     spec §12 D6）；TXT 序列化经 `_txt_exporter.to_txt(book)`（spec
     §5.3，纯函数）——本文件不 mock 序列化器，200 断言同时验证
     service→序列化→响应 全链路真实执行

7. 【错误契约（spec §3.3 异常映射表）】
   - 404：项目不存在/已软删 → `{"detail": "项目不存在"}`。service 抛
     `inkflow.domain.ports.character_errors.ProjectNotFoundError`
     （F9 既有错误类，GREEN 前可解析——本文件顶部直接 import 它），
     router 显式 except 映射（F15 先例；404 文案与 str(e) 默认消息
     「项目不存在」一致，两种实现形态断言均成立）
   - 422：`format` 非 txt（如 epub）→ Pydantic Literal["txt"] 校验错误
     （FastAPI 自动，路由前短路，service 零调用）；`include_settings`
     非法（非 bool）→ 422。Pydantic v2 错误 detail 为 list，断言
     字段名与非法值在 str(detail) 中回显（文案不钉死，随版本浮动）
   - 500：内部异常（序列化失败等）→ `{"detail": "内部错误: <e>"}`
     （F15 audit router 先例 detail=f"内部错误: {e}" 透传，精确断言）
   - 项目 ID 非法（非 UUID/非 int）→ _parse_id 解析失败短路 404
     「项目不存在」，service 零调用（assert_not_awaited）

8. 【401 契约（F19 token 中间件，spec §11 依赖）】env INKFLOW_SERVER_TOKEN
   已设置时，无 X-InkFlow-Token 头 → 401 + 精确 body
   `{"detail": "Unauthorized"}`（中间件路由前短路，不触达 handler）。
   401 用例单独使用 set_token_env fixture（test_token_auth.py 同款
   env-set 模式）——与 client fixture 的 delenv 直通模式互斥；fixture
   求值顺序 client 先 delenv、set_token_env 后 setenv，请求发出时 env
   已设置。

9. 【DB 规避】全部用例通过 patch `inkflow.api.routers.export._get_svc`
   替换服务层（mock ExportService），不触达真实 repo/DB；get_db 依赖
   仍会执行（打开会话），与 tests/api 既有测试行为一致，是既有套件
   已接受的基线。TestClient 触发 lifespan → create_tables() 在 CWD 写
   ./inkflow.db，与 tests/api 既有测试（test_health.py、test_settings_
   api.py）行为一致，已接受，不做规避。

10. 【测试断言形态】交互断言不锁实现形态：include_settings 透传断言
    读取 await_args 后同时检查位置参数与关键字参数（GREEN 传
    `svc.export(pid, include_settings=...)` 或位置参数均通过）；404
    服务层调用断言仅 assert_awaited_once（不锁参数精确值——pid 为
    解析后的 uuid.UUID 对象，非请求字符串）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.export` 模块不存在 → 本文件
【收集期 ModuleNotFoundError】collected 0 items / 1 error（exit 2），
属预期失败形态（全部用例此时均不执行；token 401 用例依赖的中间件
虽已存在，但收集期错误优先于一切用例）。GREEN 阶段：按上述契约实现
api/routers/export.py + deps.get_export_service + domain/models/output.py
+ app.py include_router 后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import (
    export,  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError

# ── 契约常量 ──
ENDPOINT = "/api/v1/projects"
"""导出端点前缀（spec §3.1）：完整路径 = {ENDPOINT}/{project_id}/export。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §11）：本文件全部用例依赖未设置 → 直通。"""

TEST_TOKEN = "test-token-53-export-aB3xQ9"
"""测试固定 token（401 用例设置 INKFLOW_SERVER_TOKEN 用）。"""

PROJECT_ID_INT = "1"
"""int 格式项目 ID（_parse_id int 分支；F1 项目 ID 数字形态）。"""

PROJECT_ID_UUID = "3f7f8a1e-9b2c-4d5e-8f6a-7b8c9d0e1f2a"
"""UUID 格式项目 ID（_parse_id UUID 分支；F1 项目 ID UUID 形态）。"""

TITLE = "我的小说"
"""测试书名（中文，验证 TXT 文本回显 + 下载文件名 URL 编码）。"""

EXPECTED_FILENAME = f"{TITLE}-txt.txt"
"""建议文件名（spec §3.1/§5.3：`{书名}-txt.txt`）。"""


# ── Fixtures ──


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient 实例（函数级，与 tests/api 既有风格一致）。

    设计假设 #2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通，
    全部用例无 token 直连；monkeypatch 自动还原，测试间互不污染。
    触发 lifespan → create_tables()，行为与 test_health.py 相同（#9）。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    return TestClient(app)


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN=TEST_TOKEN，返回 token 值。

    401 用例专用（设计假设 #8）：与 client fixture 的 delenv 直通模式
    互斥，不可同用例共存；fixture 求值顺序 client 先 delenv、
    set_token_env 后 setenv，请求发出时 env 已设置。依赖中间件每次
    请求时读 env（test_token_auth.py 设计假设 #2），app import 之后
    设置仍然有效。
    """
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


@pytest.fixture
def patched_export_service():
    """patch 模块级 _get_svc（服务工厂），返回 mock ExportService。

    与 tests/api/test_token_auth.py 的 patched_project_list_service 同款
    模式：handler 内 `_get_svc(db)` 调用模块级函数（设计假设 #3），
    patch 该名字即替换服务层；mock_service.export 由各用例设置
    return_value / side_effect。GET 请求须在 patch 生效期内发出。
    """
    with patch("inkflow.api.routers.export._get_svc") as mock_get_svc:
        mock_service = AsyncMock()
        mock_service.export = AsyncMock()
        mock_get_svc.return_value = mock_service
        yield mock_service


# ── 测试数据构造 ──


def _make_book(title: str = TITLE) -> Any:
    """构造最小 BookDocument（spec §2.2 字段契约，设计假设 #5）。

    惰性 import inkflow.domain.models.output：RED 阶段该模块不存在，
    惰性化使收集期错误只来自 inkflow.api.routers.export（单一缺失
    模块，RED 报告干净）；GREEN 阶段模块落地后此处正常解析。
    返回 1 卷 1 章的最小文档树，meta.title 可覆盖（默认 TITLE）。
    """
    from inkflow.domain.models.output import (
        BookChapter,
        BookDocument,
        BookMeta,
        BookVolume,
    )

    return BookDocument(
        meta=BookMeta(
            title=title,
            genre="玄幻",
            language="zh-CN",
            target_words=1_000_000,
            updated_at=datetime(2026, 8, 9, 12, 0, 0),
        ),
        volumes=[
            BookVolume(
                title="第一卷：序章",
                order_index=1.0,
                chapters=[
                    BookChapter(
                        title="第 1 章 开端",
                        content="（正文……）",
                        order_index=1.0,
                        word_count=5,
                    )
                ],
            )
        ],
        settings=[],
    )


def _export_call_values(mock_service) -> list:
    """mock export 最近一次调用的实参值（位置 + 关键字，不锁传参形态）。

    设计假设 #10：include_settings 透传断言同时兼容
    `svc.export(pid, include_settings=...)` 与位置参数两种 GREEN 形态。
    """
    call = mock_service.export.await_args
    assert call is not None, "export 未被调用（service 层未触达）"
    return [*call.args, *call.kwargs.values()]


# ── 200 下载契约（spec §3.1/§3.2，验收 M7）──


class TestExportDownload:
    """200 下载成功路径：响应头/文件名/文本/参数透传。"""

    def test_export_returns_txt_download(self, client, patched_export_service):
        """缺省参数 GET → 200 文本下载（Content-Type/Disposition + 文本回显）。

        断言链（设计假设 #6）：
        - Content-Type 含 text/plain 与 charset=utf-8
        - Content-Disposition 含 attachment，且 URL 编码后的
          `{书名}-txt.txt` 出现在头值中（中文文件名防破坏头）
        - 响应体 = TXT 序列化文本，书名在文本中（序列化器真实执行）
        - 缺省 include_settings=false 透传到 service（位置/关键字皆可）
        """
        patched_export_service.export.return_value = _make_book()
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export")
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/plain" in content_type
        assert "charset=utf-8" in content_type
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert quote(EXPECTED_FILENAME) in disposition
        assert TITLE in resp.text
        assert False in _export_call_values(patched_export_service)

    def test_export_format_txt_explicit(self, client, patched_export_service):
        """`format=txt` 显式传入 → 200（v1.1 唯一合法值，spec §3.1）。"""
        patched_export_service.export.return_value = _make_book()
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export?format=txt")
        assert resp.status_code == 200
        assert TITLE in resp.text

    def test_export_include_settings_true_passed_to_service(
        self, client, patched_export_service
    ):
        """`include_settings=true` → 200 且 True 透传到 service（spec §3.1）。

        Q3=C 拍板：参数切换附录（默认不含）；断言 mock export 收到
        True（位置/关键字传参形态自由，设计假设 #10）。
        """
        patched_export_service.export.return_value = _make_book()
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export?include_settings=true")
        assert resp.status_code == 200
        assert True in _export_call_values(patched_export_service)

    def test_export_uuid_project_id_ok(self, client, patched_export_service):
        """UUID 字符串项目 ID → 200（_parse_id UUID 分支，设计假设 #3）。"""
        patched_export_service.export.return_value = _make_book()
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_UUID}/export")
        assert resp.status_code == 200
        assert TITLE in resp.text


# ── 错误契约（spec §3.3 异常映射表）──


class TestExportErrors:
    """404 / 422 / 500 错误面。"""

    def test_404_project_not_found(self, client, patched_export_service):
        """service 抛 ProjectNotFoundError → 404 detail 精确「项目不存在」。

        F9 character_errors.ProjectNotFoundError 默认消息即「项目不存在」
        （设计假设 #7）；router 显式 except 映射（str(e) 或字面量两种
        GREEN 形态断言均成立）。UUID ID 同时验证解析到达 service 层
        （assert_awaited_once，不锁参数精确值）。
        """
        patched_export_service.export.side_effect = ProjectNotFoundError()
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_UUID}/export")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "项目不存在"}
        patched_export_service.export.assert_awaited_once()

    def test_404_invalid_project_id(self, client, patched_export_service):
        """非 UUID/非 int 项目 ID → 404 短路（_parse_id 解析失败）。

        解析失败在服务层之前抛出（设计假设 #3，audit.py 同款）；
        service 零调用（export 不被 await）。
        """
        resp = client.get(f"{ENDPOINT}/not-a-real-id/export")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "项目不存在"}
        patched_export_service.export.assert_not_awaited()

    def test_422_invalid_format(self, client, patched_export_service):
        """`format=epub`（非 txt）→ 422 Pydantic Literal 校验错误。

        detail 为 Pydantic v2 错误列表（isinstance list）；字段名 format
        与非法值 epub 在 str(detail) 中回显（文案不钉死，随版本浮动）。
        校验在 DTO 层短路，service 零调用。
        """
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export?format=epub")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert "format" in str(detail)
        assert "epub" in str(detail)
        patched_export_service.export.assert_not_awaited()

    def test_422_invalid_include_settings(self, client, patched_export_service):
        """`include_settings=notabool`（非法 bool）→ 422（spec §3.3）。"""
        resp = client.get(
            f"{ENDPOINT}/{PROJECT_ID_INT}/export?include_settings=notabool"
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list)
        assert "include_settings" in str(detail)

    def test_500_internal_error(self, client, patched_export_service):
        """service 抛内部异常 → 500 detail 精确 `内部错误: <e>`（ADR-012）。

        F15 audit router 先例：`except Exception → HTTPException(500,
        detail=f"内部错误: {e}")` 透传（设计假设 #3/#7）；异常消息
        「序列化失败 boom」出现在 detail 中。
        """
        patched_export_service.export.side_effect = RuntimeError("序列化失败 boom")
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "内部错误: 序列化失败 boom"}


# ── token 中间件契约（F19，spec §11 依赖）──


class TestExportTokenAuth:
    """env 已设置时导出端点受 token 保护（路由前短路）。"""

    def test_missing_token_returns_401(self, client, set_token_env):
        """INKFLOW_SERVER_TOKEN 已设置 + 无 X-InkFlow-Token 头 → 401。

        精确 body {"detail": "Unauthorized"}（无内部细节，防探测，
        test_token_auth.py 同款契约）；中间件先于路由执行，不触达
        handler。
        """
        resp = client.get(f"{ENDPOINT}/{PROJECT_ID_INT}/export")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}
