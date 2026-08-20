"""#522 P2 多形态上传 — upload-zip / upload-url 端点契约测试（GREEN 新增文件）.

本文件为父侧未覆盖的两个新端点补测（GREEN 允许新增 tests/api 文件，非修改
既有测试）：锁定任务书 §3.4 契约——zip 内存解压复用 create 流程、SKILL.md
10MB 上限、zip-slip 防护；URL httpx 异步下载（timeout=30s）、失败 422。

══════════════════ 契约锁定说明（#522 P2 §3.4）══════════════════

1. POST /api/v1/skills/upload-zip（multipart，键 file，.zip 后缀）：
   - 201 + 与 POST /skills 相同实体形状（id=name、content 逐字 roundtrip、
     source=user_upload、agent_ids=[]），且写出 skills_root/<name>/SKILL.md
   - SKILL.md 定位：根目录或任意子目录首个（info.filename.endswith('SKILL.md')）；
     文件名含 `..` 的条目跳过（zip-slip 防护，只内存读取不落盘）
   - SKILL.md 解压后 > 10MB → 422「SKILL.md 超过 10MB 上限」
   - 无 SKILL.md → 422「zip 包内未找到 SKILL.md」；非 .zip → 422「仅支持 zip 包」；
     zip 损坏 → 422「zip 包解析失败」
   - 复用 create：同名 422「同名 skill 已存在」/ frontmatter 非法 422
     「frontmatter 不合法」
2. POST /api/v1/skills/upload-url（JSON {url}）：
   - httpx 异步下载：AsyncClient().get(url, timeout=30)（锁定 timeout=30）
   - 201 + 实体契约同上；HTTP 非 2xx → 422「下载失败（HTTP {code}）」；
     网络错误 → 422「下载失败，请检查 URL」；空 URL → 422「URL 不能为空」
   - 复用 create：frontmatter 非法 / 同名 → 422（同 POST /skills）

测试方式同 test_skills_api.py：ASGITransport + AsyncClient 直连真实 app；
skills_root fixture monkeypatch config.data_dir → tmp_path；upload-url 经
monkeypatch router 模块的 AsyncClient 为可编程 fake（锁定 timeout 契约）。
"""

from __future__ import annotations

import importlib
import io
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers import (
    skills,  # 模块存在性契约（upload-zip/upload-url 在其内实现；fake_http 亦引用）
)

# ── 契约常量 ──

ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（#522 契约 #1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

DETAIL_ZIP_ONLY = "仅支持 zip 包"
DETAIL_ZIP_NO_SKILL = "zip 包内未找到 SKILL.md"
DETAIL_ZIP_TOO_LARGE = "SKILL.md 超过 10MB 上限"
DETAIL_ZIP_INVALID = "zip 包解析失败"
DETAIL_URL_EMPTY = "URL 不能为空"
DETAIL_URL_NETWORK = "下载失败，请检查 URL"
DETAIL_CONFLICT = "同名 skill 已存在"
DETAIL_FRONTMATTER = "frontmatter 不合法"

VALID_SKILL_MD = (
    "---\n"
    "name: web-research\n"
    "description: 网络调研方法论\n"
    "---\n"
    "# 调研流程\n"
    "1. 确定关键词\n"
)
"""合法 SKILL.md 样例（frontmatter name=web-research 满足 N2）。"""

INVALID_SKILL_MD = "---\ndescription: 缺 name\n---\n# 非法"
"""frontmatter 非法样例（复用 POST /skills 422 语义）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def skills_root(monkeypatch, tmp_path) -> Path:
    """skills root: tmp_path/skills + config.data_dir redirect."""
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


class _FakeResponse:
    """模拟 httpx.Response（仅暴露端点使用的 status_code/text/raise_for_status）。"""

    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://fake"),
                response=httpx.Response(self.status_code, text=self.text),
            )


class _FakeAsyncClient:
    """可编程 AsyncClient 替身：记录 (url, timeout) 调用，按序返回响应或抛错。"""

    def __init__(self) -> None:
        self.responses: list[_FakeResponse] = []
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, url: str, timeout: object) -> _FakeResponse:
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@pytest.fixture
def fake_http(monkeypatch) -> _FakeAsyncClient:
    """monkeypatch router 模块的 AsyncClient 为可编程 fake（锁定 timeout=30 契约）。"""
    fake = _FakeAsyncClient()
    monkeypatch.setattr(skills, "AsyncClient", lambda *args, **kwargs: fake)
    return fake


# ── Seed / 断言辅助 ──


def _write_skill(root: Path, name: str, *, description: str = "方法论描述") -> Path:
    """向 skills_root 写入 `skills/<name>/SKILL.md`（同名冲突用例造数）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name} 正文\n"
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return d


def _make_zip(entries: dict[str, bytes]) -> bytes:
    """内存构造 zip（entries: {zip 内部路径: 字节内容}，不解压落盘）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _skill_zip(content: str = VALID_SKILL_MD) -> bytes:
    """根目录 SKILL.md 的 zip 字节。"""
    return _make_zip({"SKILL.md": content.encode("utf-8")})


def _assert_detail_contract(data: dict) -> None:
    """实体响应契约（同 POST /skills）：8 键 + id==name + 值语义。"""
    for key in (
        "id",
        "name",
        "description",
        "content",
        "source",
        "created_at",
        "updated_at",
        "agent_ids",
    ):
        assert key in data, f"响应缺少契约字段 {key}"
    assert data["id"] == data["name"], "id must equal name"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["description"], str)
    assert isinstance(data["content"], str) and data["content"]
    assert data["source"] in ("builtin", "user_upload")
    datetime.fromisoformat(data["created_at"])
    datetime.fromisoformat(data["updated_at"])
    assert isinstance(data["agent_ids"], list)


# ── POST /api/v1/skills/upload-zip（§3.4 契约）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUploadSkillZip:
    """upload-zip 端点契约（multipart file，内存解压复用 create 流程）。"""

    async def test_upload_zip_201_contract(
        self, client, db_session, override_get_db, skills_root
    ):
        """zip 根目录 SKILL.md → 201 + 实体契约 + content 逐字 + 落盘 SKILL.md。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={"file": ("web-research.zip", _skill_zip(), "application/zip")},
        )
        assert resp.status_code == 201
        data = resp.json()
        _assert_detail_contract(data)
        assert data["name"] == "web-research"
        assert data["description"] == "网络调研方法论"
        assert data["content"] == VALID_SKILL_MD
        assert data["source"] == "user_upload"
        assert data["agent_ids"] == []
        f = skills_root / "web-research" / "SKILL.md"
        assert f.is_file(), "上传后必须写出文件"
        assert f.read_text(encoding="utf-8") == VALID_SKILL_MD

    async def test_upload_zip_skill_md_in_subdirectory(
        self, client, db_session, override_get_db, skills_root
    ):
        """任意子目录首个 SKILL.md（endswith 匹配）→ 201 + 正常落盘。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={
                "file": (
                    "bundle.zip",
                    _make_zip({"docs/skills/SKILL.md": VALID_SKILL_MD.encode("utf-8")}),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "web-research"
        assert data["content"] == VALID_SKILL_MD
        assert (skills_root / "web-research" / "SKILL.md").is_file()

    async def test_upload_zip_without_skill_md_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """zip 内无 SKILL.md → 422「zip 包内未找到 SKILL.md」，不产生目录。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={
                "file": (
                    "empty.zip",
                    _make_zip({"README.md": b"no skill"}),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_ZIP_NO_SKILL
        assert not (skills_root / "web-research").exists()

    async def test_upload_zip_path_traversal_entry_skipped_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """仅含 `../evil/SKILL.md`（路径穿越）→ 跳过该条目 → 422 未找到；不落盘。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={
                "file": (
                    "evil.zip",
                    _make_zip({"../evil/SKILL.md": VALID_SKILL_MD.encode("utf-8")}),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_ZIP_NO_SKILL
        assert not (skills_root / "web-research").exists()
        assert not (skills_root.parent / "evil").exists()

    async def test_upload_zip_invalid_frontmatter_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """SKILL.md frontmatter 非法 → 422「frontmatter 不合法」（同 POST /skills）。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={
                "file": (
                    "bad.zip",
                    _skill_zip(content=INVALID_SKILL_MD),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_FRONTMATTER
        assert not (skills_root / "web-research").exists()

    async def test_upload_zip_duplicate_name_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """同名目录已存在 → 422「同名 skill 已存在」（复用 create 语义）。"""
        _write_skill(skills_root, "web-research", description="已存在")
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={"file": ("web-research.zip", _skill_zip(), "application/zip")},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_CONFLICT

    async def test_upload_non_zip_file_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """非 .zip 文件 → 422「仅支持 zip 包」。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={
                "file": ("SKILL.md", VALID_SKILL_MD.encode("utf-8"), "text/markdown")
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_ZIP_ONLY

    async def test_upload_zip_skill_md_too_large_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """SKILL.md 解压后 > 10MB → 422「SKILL.md 超过 10MB 上限」（防护）。"""
        big = _skill_zip(content="x" * (10 * 1024 * 1024 + 1))
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={"file": ("big.zip", big, "application/zip")},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_ZIP_TOO_LARGE
        assert list(skills_root.iterdir()) == []

    async def test_upload_zip_bad_zip_422(
        self, client, db_session, override_get_db, skills_root
    ):
        """损坏的 zip 字节 → 422「zip 包解析失败」。"""
        resp = await client.post(
            f"{ENDPOINT}/upload-zip",
            files={"file": ("broken.zip", b"not a zip", "application/zip")},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_ZIP_INVALID


# ── POST /api/v1/skills/upload-url（§3.4 契约）──


@pytest.mark.asyncio
@pytest.mark.api
class TestUploadSkillUrl:
    """upload-url 端点契约（httpx 下载 timeout=30，失败 422）。"""

    GOOD_URL = "https://example.com/skills/web-research/SKILL.md"

    async def test_upload_url_201_contract_with_timeout_30(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """下载成功 → 201 + 实体契约 + 落盘；锁定 get(url, timeout=30) 契约。"""
        fake_http.responses.append(_FakeResponse(200, VALID_SKILL_MD))
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": self.GOOD_URL})
        assert resp.status_code == 201
        data = resp.json()
        _assert_detail_contract(data)
        assert data["name"] == "web-research"
        assert data["content"] == VALID_SKILL_MD
        assert data["source"] == "user_upload"
        assert (skills_root / "web-research" / "SKILL.md").is_file()
        assert fake_http.calls == [(self.GOOD_URL, 30)], "httpx 下载必须带 timeout=30"

    async def test_upload_url_http_error_422(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """HTTP 404 → 422「下载失败（HTTP 404）」，不落盘。"""
        fake_http.responses.append(_FakeResponse(404, "not found"))
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": self.GOOD_URL})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "下载失败（HTTP 404）"
        assert list(skills_root.iterdir()) == []

    async def test_upload_url_network_error_422(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """网络/超时错误 → 422「下载失败，请检查 URL」。"""
        fake_http.error = httpx.RequestError(
            "connect timeout", request=httpx.Request("GET", self.GOOD_URL)
        )
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": self.GOOD_URL})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_URL_NETWORK
        assert list(skills_root.iterdir()) == []

    async def test_upload_url_invalid_frontmatter_422(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """下载内容 frontmatter 非法 → 422「frontmatter 不合法」（同 POST /skills）。"""
        fake_http.responses.append(_FakeResponse(200, INVALID_SKILL_MD))
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": self.GOOD_URL})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_FRONTMATTER
        assert list(skills_root.iterdir()) == []

    async def test_upload_url_duplicate_422(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """同名目录已存在 → 422「同名 skill 已存在」（复用 create 语义）。"""
        _write_skill(skills_root, "web-research", description="已存在")
        fake_http.responses.append(_FakeResponse(200, VALID_SKILL_MD))
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": self.GOOD_URL})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_CONFLICT

    async def test_upload_url_empty_422(
        self, client, db_session, override_get_db, skills_root, fake_http
    ):
        """空 URL（含纯空白）→ 422「URL 不能为空」，不发下载请求。"""
        resp = await client.post(f"{ENDPOINT}/upload-url", json={"url": "   "})
        assert resp.status_code == 422
        assert resp.json()["detail"] == DETAIL_URL_EMPTY
        assert fake_http.calls == []
