"""S3f-T4 R3 契约：整数据目录复制 = 备份恢复双轨（issue #869 / contract-s3f-t4.md §1 R3）。

镜像先例：test_rag_vector_consistency_journey.py（真 sqlite + 真 chroma tmp +
BagEmbeddings 字符袋确定性向量类，L50-72 直接 import 复用）+ test_cli_blackbox.py
（子进程真内核 + _skip_ci 守卫 + taskkill 回收）+ test_database_migration_chain.py
（lifespan 全局重定向手法）。

1. 进程内轨（CI 计入覆盖）：tmp dirA 真 sqlite 文件库 → 完整 lifespan（迁移链+seed）
   → 建项目 + 3 章 → reindex（真实仓储面 + 真实 chroma + 指纹）→ 指纹 fresh +
   检索基线 → dispose + shutil.copytree(dirA, dirB) → 新 engine 指 dirB 重跑完整
   lifespan（幂等）→ repo 读项目/章完整 + LangChainVectorStore(dirB/chroma) 检索
   命中同结果（top hit 一致）+ 指纹 compare == fresh（无重建 → 备份恢复语义）。
2. 子进程黑盒轨（CI skip）：subprocess serve env=dirA → port-file READY 解析 →
   真 HTTP（X-InkFlow-Token）建项目 + /health 200 → taskkill /T /F 停 →
   copytree dirB → 新 serve env=dirB → GET /projects 项目仍在 + /health 200。
   断言 = 备份迁移语义（用户实际用法）；DB-only（向量面由进程内轨锁定）。

进程内轨不依赖 T3 fake embedding（BagEmbeddings 自带确定性向量）。
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.config import config
from inkflow.domain.models.vector_fingerprint import VectorFingerprint
from inkflow.domain.ports.vector_store import EntityType
from inkflow.domain.services._chunking import ChunkingConfig, ChunkingMode
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.vector_fingerprint import (
    build_fingerprint,
    compare_fingerprints,
)
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

app_module = importlib.import_module("inkflow.api.app")

# BagEmbeddings 镜像先例 import（backend/tests 不入 pytest sys.path：显式插入后按模块 import，
# 不重写该确定性向量类——任务约束「直接 import 复用勿重写」）
_BACKEND_TESTS_DIR = Path(__file__).resolve().parents[2] / "backend" / "tests"
if str(_BACKEND_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_TESTS_DIR))
from unit.test_rag_vector_consistency_journey import BagEmbeddings  # noqa: E402

EMBED_MODEL = "m1"
EMBED_DIM = 128
CHUNK_SIZE = 200
PROJECT_NAME = "备份恢复之书"
CH_TITLES = ["卷一·玄明出山", "卷二·宁晚悟剑", "卷三·剑冢轰鸣"]

_SENTENCES = [
    "玄明御剑而行踏雪寻梅于蜀山之巅，剑气纵横三千里，霜雪纷纷退避。",
    "宁晚静坐崖边参悟剑意，云海翻涌不息，霜雪覆眉而不自知。",
    "剑冢深处万剑齐鸣，锈剑亦藏锋芒，万道剑气回应天地长啸。",
]


def _long_content(index: int) -> str:
    """跨多 FIXED 块长章节（句号边界密集；各章字符袋显著不同 → 检索 top hit 确定）。"""
    return "".join(_SENTENCES[index] for _ in range(25))


def _model_cfg() -> dict:
    return {"provider": "fake", "model_id": EMBED_MODEL, "base_url": "https://x.test/v1"}


def _chunking_cfg() -> dict:
    return {"mode": "fixed", "chunk_size": CHUNK_SIZE, "overlap_ratio": 0.0}


def _configured_fp_dict() -> dict:
    """configured 指纹 dict（fingerprint_provider 返回形态，走真实 build_fingerprint）。"""
    return build_fingerprint(_model_cfg(), _chunking_cfg(), dimension=EMBED_DIM).model_dump()


def _make_real_service(
    store: LangChainVectorStore,
    fingerprint: dict,
    *,
    chapter_repo,
    project_repo,
) -> ExtractionService:
    """装配真实 vector_store + 真章节/项目仓储的 ExtractionService（镜像 journey
    make_service，仅 CHAPTER_CHUNK 旅程；其余端口 mock 保持最小面）。"""
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=AsyncMock(),
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        character_repo=None,
        world_repo=None,
        timeline_repo=None,
        foreshadowing_repo=None,
        vector_store=store,
        fingerprint_provider=AsyncMock(return_value=fingerprint),
        chunking=ChunkingConfig(mode=ChunkingMode.FIXED, chunk_size=CHUNK_SIZE, overlap_ratio=0.0),
    )


def _make_engine(db_file: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    event.listen(engine.sync_engine, "connect", db_module._set_sqlite_pragma)
    return engine


def _make_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@contextlib.asynccontextmanager
async def _redirect_globals(engine, factory, data_dir: Path):
    """重定向 lifespan 全局（engine/factory/data_dir），退出还原（镜像 D1 fixture）。

    ⚠️ 双换：``db_module.engine`` 与 ``app_module.engine`` /
    ``app_module.async_session_factory``（app.py from-import 独立绑定）。"""
    saved = (
        db_module.engine,
        db_module.async_session_factory,
        app_module.engine,
        app_module.async_session_factory,
        config.data_dir,
    )
    db_module.engine = engine
    db_module.async_session_factory = factory
    app_module.engine = engine
    app_module.async_session_factory = factory
    config.data_dir = data_dir
    try:
        yield
    finally:
        await engine.dispose()
        (
            db_module.engine,
            db_module.async_session_factory,
            app_module.engine,
            app_module.async_session_factory,
            config.data_dir,
        ) = saved


async def _run_lifespan(engine) -> None:
    """完整驱动一次 app lifespan（create_all + ensure 链 + seed + scheduler）。"""
    fake_app = SimpleNamespace(state=SimpleNamespace())
    async with app_module.lifespan(fake_app):
        pass


async def _seed_project_and_chapters(factory, pid_uuid: uuid.UUID) -> int:
    """项目 + 3 章（长中文正文）落真 sqlite 文件库；返回项目 int 主键。"""
    async with factory() as session:
        project = ProjectORM(name=PROJECT_NAME, language="zh-CN", target_words=300_000)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        pid_int = project.id
        assert pid_int == pid_uuid.int
        for i, title in enumerate(CH_TITLES, start=1):
            session.add(
                ChapterORM(
                    project_id=pid_int,
                    title=title,
                    content=_long_content(i - 1),
                    order_index=float(i),
                )
            )
        await session.commit()
        return pid_int


# ── 子进程黑盒轨 helpers ──


def _skip_ci() -> bool:
    return os.environ.get("CI") == "true"


def _kill_kernel_tree(pid: int) -> None:
    """可靠终止进程树（Windows taskkill /T /F；best-effort，镜像 test_cli_blackbox）。"""
    if pid <= 0:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


def _spawn_serve(data_dir: Path, port_file: Path) -> subprocess.Popen:
    """拉起真实内核（python -m inkflow serve），env 显式注入 INKFLOW_DATA_DIR。"""
    env = os.environ.copy()
    env["INKFLOW_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    env.pop("INKFLOW_SERVER_TOKEN", None)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "inkflow",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--port-file",
            str(port_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _wait_kernel_state(port_file: Path, proc: subprocess.Popen, timeout: float) -> dict:
    """轮询 --port-file（F19 四字段交付）直至合法 JSON；进程秒退/超时 → 抛。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"serve 进程提前退出 returncode={proc.returncode}")
        try:
            payload = json.loads(port_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and {"port", "token", "pid"} <= set(payload):
                return payload
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise TimeoutError(f"等待内核就绪超时（{timeout:.0f}s）：{port_file}")


def _http_json(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    """真 HTTP 请求（X-InkFlow-Token 鉴权，spec §2.1.3/§2.3.1）。"""
    req = urllib.request.Request(url, method=method)
    req.add_header("X-InkFlow-Token", token)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data, timeout=30) as resp:
        raw = resp.read()
    body = json.loads(raw.decode("utf-8")) if raw else {}
    return resp.status, body


# ── 进程内轨（CI 计入覆盖） ──


@pytest.mark.asyncio  # repo-root tests/ 树 rootdir=仓库根 → pytest-asyncio STRICT 需显式 mark
async def test_data_dir_copy_backup_restore_inprocess(tmp_path: Path) -> None:
    """整目录复制 = 备份恢复：dirA 建库+索引 → copytree → dirB 重跑 lifespan →
    repo 读完整 + 检索命中同结果 + 指纹 fresh（无重建）。"""
    dir_a = tmp_path / "dirA"
    dir_a.mkdir()
    dir_b = tmp_path / "dirB"
    pid_uuid = uuid.UUID(int=1)

    # ① dirA：真 sqlite 文件库 + 完整 lifespan（迁移链 + seed，镜像用户真实启动）
    engine_a = _make_engine(dir_a / "inkflow.db")
    factory_a = _make_factory(engine_a)
    async with _redirect_globals(engine_a, factory_a, dir_a):
        await _run_lifespan(engine_a)

    # ② 项目 + 3 章（真 ORM 落库）
    pid_int = await _seed_project_and_chapters(factory_a, pid_uuid)

    # ③ reindex（真仓储面 + 真 chroma + 指纹写入）：指纹 fresh、检索基线
    store_a = LangChainVectorStore(dir_a / "chroma", BagEmbeddings(EMBED_DIM, EMBED_MODEL))
    async with factory_a() as session:
        svc = _make_real_service(
            store_a,
            _configured_fp_dict(),
            chapter_repo=SQLiteChapterRepository(session),
            project_repo=SQLiteProjectRepository(session),
        )
        result = await svc.reindex(pid_uuid, entity_types=[EntityType.CHAPTER_CHUNK])
    assert result.indexed > 0
    assert result.collections_recreated is False
    fp_a = await store_a.read_fingerprint(str(pid_uuid))
    assert fp_a is not None and fp_a["status"] == "fresh"
    assert fp_a["embedding"]["model_id"] == EMBED_MODEL
    hits_a = await store_a.retrieve(
        "玄明御剑而行踏雪寻梅",
        project_id=str(pid_uuid),
        entity_types=[EntityType.CHAPTER_CHUNK],
        top_k=5,
        min_score=0.01,
    )
    assert hits_a and hits_a[0].relevance_score > 0.5
    top_a = hits_a[0].entity_id
    # 停服语义：dispose 落盘 checkpoint 后再复制整目录
    await engine_a.dispose()
    shutil.copytree(dir_a, dir_b)

    # ④ dirB：新 engine + 完整 lifespan 重跑（幂等：create_all no-op / ensure no-op /
    #    seed 同名跳过——备份后启动等价用户正常重启）
    engine_b = _make_engine(dir_b / "inkflow.db")
    factory_b = _make_factory(engine_b)
    async with _redirect_globals(engine_b, factory_b, dir_b):
        await _run_lifespan(engine_b)

        # ⑤ repo 读项目/章完整
        async with factory_b() as session:
            project = await SQLiteProjectRepository(session).get(pid_int)
            assert project is not None
            assert project.name == PROJECT_NAME
            chapters, total = await SQLiteChapterRepository(session).list_chapters(
                pid_int, offset=0, limit=50
            )
            assert total == 3
            assert [c.title for c in chapters] == CH_TITLES
            # seed 幂等（备份目录里的 seed 数据未被二次启动破坏/翻倍）
            assert (
                await session.execute(text("SELECT COUNT(*) FROM provider_configs"))
            ).scalar() == 4
            assert (await session.execute(text("SELECT COUNT(*) FROM agents"))).scalar() == 6

    # ⑥ 新 store 指 dirB/chroma：检索命中同结果 + 指纹 compare == fresh（无重建）
    store_b = LangChainVectorStore(dir_b / "chroma", BagEmbeddings(EMBED_DIM, EMBED_MODEL))
    hits_b = await store_b.retrieve(
        "玄明御剑而行踏雪寻梅",
        project_id=str(pid_uuid),
        entity_types=[EntityType.CHAPTER_CHUNK],
        top_k=5,
        min_score=0.01,
    )
    assert hits_b and hits_b[0].entity_id == top_a
    stored_b = await store_b.read_fingerprint(str(pid_uuid))
    assert stored_b is not None and stored_b["status"] == "fresh"
    stale, reason = compare_fingerprints(
        VectorFingerprint.model_validate(_configured_fp_dict()),
        VectorFingerprint.model_validate(stored_b),
    )
    assert stale is False, f"dirB 指纹与配置不一致（应 fresh 无重建）: {reason}"


# ── 子进程黑盒轨（CI skip，本地验证） ──


class TestDataDirRecoveryBlackbox:
    """黑盒备份恢复：真实子进程内核 × 两个数据目录（镜像 test_cli_blackbox 形态）。"""

    @pytest.mark.skipif(
        _skip_ci(), reason="GitHub Actions 沙箱无法拉起真实内核（秒退）；本地黑盒验证"
    )
    def test_serve_restart_after_data_dir_copy(self, tmp_path) -> None:
        """serve(dirA) 建项目 → 停 → copytree → serve(dirB) → 项目仍在 + /health 200。"""
        dir_a = tmp_path / "dirA"
        dir_a.mkdir()
        dir_b = tmp_path / "dirB"
        pf_a = tmp_path / "kernelA.json"
        pf_b = tmp_path / "kernelB.json"
        proc_a: subprocess.Popen | None = None
        proc_b: subprocess.Popen | None = None
        try:
            # ① dirA 内核 + 真 HTTP 建项目
            proc_a = _spawn_serve(dir_a, pf_a)
            state_a = _wait_kernel_state(pf_a, proc_a, timeout=90.0)
            base_a = f"http://127.0.0.1:{state_a['port']}"
            status, body = _http_json(
                "POST",
                f"{base_a}/api/v1/projects",
                state_a["token"],
                {"name": "黑盒恢复项目", "language": "zh-CN"},
            )
            assert status == 201, body
            assert body["name"] == "黑盒恢复项目"
            status, _ = _http_json("GET", f"{base_a}/health", state_a["token"])
            assert status == 200

            # ② 停服（taskkill 树）→ 复制整个数据目录（备份迁移语义）
            _kill_kernel_tree(int(state_a["pid"]))
            proc_a = None
            shutil.copytree(dir_a, dir_b)

            # ③ dirB 新内核：项目仍在 + /health 200
            proc_b = _spawn_serve(dir_b, pf_b)
            state_b = _wait_kernel_state(pf_b, proc_b, timeout=90.0)
            base_b = f"http://127.0.0.1:{state_b['port']}"
            status, listing = _http_json("GET", f"{base_b}/api/v1/projects", state_b["token"])
            assert status == 200
            names = [item["name"] for item in listing.get("items", [])]
            assert "黑盒恢复项目" in names, f"备份目录恢复后项目丢失: {names}"
            status, _ = _http_json("GET", f"{base_b}/health", state_b["token"])
            assert status == 200
        finally:
            if proc_a is not None:
                _kill_kernel_tree(proc_a.pid)
            if proc_b is not None:
                _kill_kernel_tree(proc_b.pid)
