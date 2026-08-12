"""#266 0.7.0 方案 A — data-dir 端点 API 测试契约（GET/PUT /api/v1/settings/data-dir）。

从 test_settings_api.py 拆分（2026-08-12：该文件 1032 行超 CI check_file_length
900 护栏——#266 段独立成文件，父侧裁定；coverage-backend 目录 glob 自动收集，
无需 ci.yml 登记）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app）；settings 路由 = 既有模块 inkflow.api.routers.settings
   （F19 已实现），本文件只测 #266 新增两端点。

2. 【无 token 模式——硬性契约】本文件全部用例依赖 env INKFLOW_SERVER_TOKEN
   未设置时中间件直通（test_token_auth.py 设计假设 #6 同款）：client fixture
   内显式 monkeypatch.delenv，免疫开发者本机 shell 的 env 残留导致假失败。

3. 【端点契约】新增两端点（挂既有 settings router，prefix=/api/v1/settings）：
   - GET  /api/v1/settings/data-dir → 200 + {"data_dir": str(config.data_dir),
     "instance_env_path": str(get_instance_env_path())}
   - PUT  /api/v1/settings/data-dir，body {"data_dir": str} → 200 +
     {"data_dir": <expanduser+resolve 绝对路径 str>, "restart_required": true}；
     写入语义 = 调 inkflow.core.config.save_instance_env(data_dir: Path)
     （GREEN：mkdir 锚点父目录 + data_dir 目录 + 写 instance.env 一行
     INKFLOW_DATA_DIR=<abs>，返回绝对路径 Path）
   - data_dir 空白（strip 后空）→ 422（Pydantic field_validator，detail 为
     校验错误列表）
   - save_instance_env 抛 OSError → 500 + {"detail": "数据目录保存失败，请
     稍后重试"}（ADR-012 通用文案风格，内部细节不泄漏）

4. 【锚点控制铁律】monkeypatch.setattr(settings, "<名>", <fn>, raising=False)
   ——settings 模块对象在文件头 import；raising=False 保证 RED 阶段属性
   不存在不报错（unittest.mock.patch 字符串路径 → setup AttributeError →
   ERROR 而非断言 FAIL），GREEN 阶段覆盖 router 模块绑定名 → handler 模块
   全局查找命中。
   【PUT 锚点例外——父侧 2026-08-12 修正】PUT handler 调 save_instance_env
   （settings 绑定），其内部锚点解析是 config 模块全局查找 get_instance_env_path
   ——必须 patch 【inkflow.core.config 模块】属性才命中（实测 patch settings
   绑定名无效 → 写入真实 %APPDATA% 污染）。与 test_config_instance_env.py
   单测隔离模式一致。

5. 【401 契约】env INKFLOW_SERVER_TOKEN 已设置时，GET /data-dir 无 token 头
   → 401 + 精确 body {"detail": "Unauthorized"}（F19 token 中间件既有实现，
   路由前短路，不触达 handler）。401 用例单独使用 set_token_env fixture
   （test_token_auth.py 同款 env-set 模式）——与 client fixture 的 delenv
   直通模式互斥，fixture 求值顺序 client 先 delenv、set_token_env 后 setenv，
   请求发出时 env 已设置。

6. 【RED 阶段预期】settings router 已存在但无 /data-dir 路由 → 本段用例除
   test_get_data_dir_without_token_401（token 中间件既有实现，预期 PASS，
   刻意守护）外全部 FAIL（请求 404 Not Found，断言失败无 ERROR）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import settings

# ── 契约常量 ──
ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

ENDPOINT_DATA_DIR = "/api/v1/settings/data-dir"
"""data-dir 端点（#266 0.7.0 方案 A 拍板）：GET 查询 / PUT 更新数据目录。"""

TEST_TOKEN = "test-token-266-data-dir"
"""401 用例固定 token（test_token_auth.py set_token_env 同款 env-set 模式）。"""


# ── Fixtures（镜像 test_settings_api.py 既有形态）──


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient 实例（函数级，与 tests/api 既有风格一致）。

    设计假设 #2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    monkeypatch 自动还原，测试间互不污染。触发 lifespan → create_tables()。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    return TestClient(app)


@pytest.fixture
def set_token_env(monkeypatch):
    """设置 INKFLOW_SERVER_TOKEN（test_token_auth.py 同款 env-set fixture）。

    设计假设 #5：401 用例专用；与 client fixture 的 delenv 直通模式互斥
    （fixture 求值顺序 client 先 delenv、本 fixture 后 setenv → 请求发出时
    env 已设置，token 中间件进入校验分支）。
    """
    monkeypatch.setenv(ENV_TOKEN, TEST_TOKEN)
    return TEST_TOKEN


# ── GET/PUT /api/v1/settings/data-dir（#266 0.7.0 方案 A）──


class TestSettingsDataDir:
    """#266 数据目录端点契约（0.7.0 方案 A，父侧 2026-08-12 定稿）。

    契约逐条（对应下方用例）：
    - GET /api/v1/settings/data-dir → 200 + {"data_dir": str(config.data_dir),
      "instance_env_path": str(get_instance_env_path())}
    - PUT /api/v1/settings/data-dir {"data_dir": str} → 200 + {"data_dir":
      <expanduser+resolve 绝对路径 str>, "restart_required": true}；写入语义 =
      调 inkflow.core.config.save_instance_env(data_dir: Path)（GREEN：mkdir
      锚点父目录 + data_dir 目录 + 写 instance.env 一行 INKFLOW_DATA_DIR=
      <abs>，返回绝对路径 Path）
    - data_dir 空白（strip 后空）→ 422（Pydantic field_validator，detail 为
      校验错误列表）
    - save_instance_env 抛 OSError → 500 + {"detail": "数据目录保存失败，请
      稍后重试"}（ADR-012 通用文案风格，内部细节不泄漏）

    【锚点控制铁律】monkeypatch.setattr(settings, "<名>", <fn>, raising=False)：
    settings 模块对象已在文件头 import；raising=False 保证 RED 阶段属性不存在
    不报错（unittest.mock.patch 字符串路径 → setup AttributeError → ERROR 而
    非断言 FAIL），GREEN 阶段覆盖 router 模块绑定名 → handler 模块全局查找命中。
    【PUT 锚点例外】PUT handler 调 save_instance_env（settings 绑定），其内部
    锚点解析是 config 模块全局查找 get_instance_env_path——必须 patch
    inkflow.core.config 模块属性才命中（实测 patch settings 绑定名无效 →
    写入真实 %APPDATA% 污染，父侧 2026-08-12 修正）。
    【RED 阶段预期】settings router 已存在但无 /data-dir 路由 → 本段用例除
    test_get_data_dir_without_token_401（token 中间件既有实现，预期 PASS，
    刻意守护）外全部 FAIL（请求 404 Not Found，断言失败无 ERROR）。
    """

    def test_get_data_dir_returns_current(self, client, tmp_path, monkeypatch):
        """GET /data-dir → 200 + data_dir 等于 config.data_dir、锚点路径回显。

        config 用函数内 lazy import（inkflow.core.config 模块级单例，动态读
        当前值免疫本机环境）；锚点经 monkeypatch.setattr 注入 settings 模块
        绑定名（GREEN 后 handler 模块全局查找命中）。
        """
        anchor = tmp_path / "InkFlow" / "instance.env"
        monkeypatch.setattr(
            settings, "get_instance_env_path", lambda: anchor, raising=False
        )
        from inkflow.core.config import config

        resp = client.get(ENDPOINT_DATA_DIR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_dir"] == str(config.data_dir)
        assert body["instance_env_path"] == str(anchor)

    def test_put_data_dir_writes_instance_env(self, client, tmp_path, monkeypatch):
        """PUT {"data_dir": <custom>} → 200 + 绝对路径 + restart_required；instance.env 落盘。

        锚点 patch 目标 = 【inkflow.core.config 模块】而非 settings 模块绑定名：
        PUT handler 调 save_instance_env（settings 绑定），其内部锚点解析是
        config 模块全局查找 get_instance_env_path——patch config 模块属性才命中
        （Batch 2 实测：patch settings 绑定名无效 → 写入真实 %APPDATA% 污染，
        父侧 2026-08-12 修正）。与 test_config_instance_env.py 单测隔离模式一致。
        """
        import importlib

        anchor = tmp_path / "InkFlow" / "instance.env"
        core_config_mod = importlib.import_module("inkflow.core.config")
        monkeypatch.setattr(
            core_config_mod,
            "get_instance_env_path",
            lambda: anchor,
            raising=False,
        )
        target = tmp_path / "custom-data"

        resp = client.put(ENDPOINT_DATA_DIR, json={"data_dir": str(target)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_dir"] == str(target.resolve())
        assert body["restart_required"] is True
        assert anchor.parent.is_dir()
        assert anchor.is_file()
        content = anchor.read_text(encoding="utf-8")
        assert f"INKFLOW_DATA_DIR={target.resolve()}" in content
        assert target.is_dir()

    def test_put_data_dir_blank_422(self, client):
        """PUT {"data_dir": "   "} → 422 + detail 为校验错误列表（field_validator）。"""
        resp = client.put(ENDPOINT_DATA_DIR, json={"data_dir": "   "})
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    def test_put_data_dir_oserror_500(self, client, tmp_path, monkeypatch):
        """save_instance_env 抛 OSError → 500 + 通用文案，内部细节不泄漏（ADR-012）。"""

        def _boom(*_args):
            raise OSError("disk full")

        monkeypatch.setattr(settings, "save_instance_env", _boom, raising=False)
        resp = client.put(ENDPOINT_DATA_DIR, json={"data_dir": str(tmp_path / "x")})
        assert resp.status_code == 500
        assert resp.json()["detail"] == "数据目录保存失败，请稍后重试"
        assert "disk full" not in resp.text

    def test_get_data_dir_without_token_401(self, client, set_token_env):
        """env 已设置 + 无 token 头 → GET /data-dir 401（全站 token 中间件既有实现）。

        守护用例：token 中间件在路由前拦截 → RED 阶段即 PASS（刻意，与
        TestSettingsTokenAuth 同规则）。
        """
        resp = client.get(ENDPOINT_DATA_DIR)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}
