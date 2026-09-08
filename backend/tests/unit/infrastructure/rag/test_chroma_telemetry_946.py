"""#946 RED 契约：chromadb 匿名遥测关闭（anonymized_telemetry=False）。

缺陷背景：chromadb（RAG 向量库，1.5.9 传递依赖）自带 OpenTelemetry 遥测，
``chromadb.config.Settings.anonymized_telemetry`` 默认 ``True``（实测
``Settings.model_fields["anonymized_telemetry"].default is True``）；``PersistentClient``
未显式传 ``settings`` 时按默认启动遥测客户端，经 OTLP 上报到外部（本地运行数据外泄）。

目标（issue #946）：``LangChainVectorStore`` 的**所有** chromadb 客户端创建路径
（实体 collection 路径 ``_get_collection`` + 指纹 meta collection 路径
``_get_meta_collection``）统一传 ``Settings(anonymized_telemetry=False)``，
确保本地运行数据不出本机。

【R】= 当前必 FAIL；【G】= 回归守护。
形态：
- R1/R2 = mock 构造验证（patch ``chromadb.PersistentClient``，断言构造入参 settings 关闭）；
- R3/R4 = 真实 chroma（tmp 目录）生效终判据（断言客户端 ``get_settings()`` 为 False）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.embeddings import Embeddings

from inkflow.domain.ports.vector_store import EntityType, IndexableEntity
from inkflow.infrastructure.rag.langchain_vector_store import LangChainVectorStore

PROJECT = "p-946"
_PERSISTENT_CLIENT = "inkflow.infrastructure.rag.langchain_vector_store.chromadb.PersistentClient"


class FakeEmbeddings(Embeddings):
    """确定性伪 Embedding — 384 维字符袋向量（与 test_langchain_vector_store.py 同规则）。"""

    dimension = 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量生成确定性向量。"""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量（与 embed_documents 同规则，保证可断言排序）。"""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """字符袋向量: 每个字符按 ord(ch) % dimension 累加计数。"""
        vec = [0.0] * self.dimension
        for ch in text:
            vec[ord(ch) % self.dimension] += 1.0
        return vec


def _mock_embeddings() -> MagicMock:
    """计数/返回值可控的 embeddings mock（mock 构造路径不触发真实 embed）。"""
    embeddings = MagicMock()
    embeddings.embed_documents.return_value = [[0.1] * 8]
    embeddings.embed_query.return_value = [0.1] * 8
    return embeddings


def _store(persist_root: Path, embeddings: Embeddings) -> LangChainVectorStore:
    """构造指向 tmp 目录的向量存储（懒加载，构造期不建客户端）。"""
    return LangChainVectorStore(persist_dir=persist_root / "chroma", embeddings=embeddings)


def _entity() -> IndexableEntity:
    """单条角色实体（真实 chroma 路径用）。"""
    return IndexableEntity(
        id="e-946",
        entity_type=EntityType.CHARACTER,
        project_id=PROJECT,
        content="蜀山掌门李英琼",
        metadata={"name": "李英琼"},
    )


class TestClientCreationPassesTelemetryOff:
    """R1/R2 — 两条客户端创建路径的构造入参必须显式关闭遥测（mock 构造验证）。"""

    async def test_r1_entity_collection_path_passes_telemetry_off(self, tmp_path: Path) -> None:
        """实体 collection 懒初始化（_get_collection）→ PersistentClient(settings=...) 关闭。"""
        with patch(_PERSISTENT_CLIENT, return_value=MagicMock()) as client_cls:
            store = _store(tmp_path, _mock_embeddings())
            await store.index(_entity())
        settings = client_cls.call_args.kwargs.get("settings")
        assert settings is not None, "#946 实体路径创建 chromadb 客户端必须显式传 settings"
        assert settings.anonymized_telemetry is False, "#946 匿名遥测必须关闭"

    async def test_r2_meta_collection_path_passes_telemetry_off(self, tmp_path: Path) -> None:
        """指纹 meta collection 懒初始化（_get_meta_collection）→ 同款关闭遥测。"""
        with patch(_PERSISTENT_CLIENT, return_value=MagicMock()) as client_cls:
            store = _store(tmp_path, _mock_embeddings())
            await store.read_fingerprint(PROJECT)
        settings = client_cls.call_args.kwargs.get("settings")
        assert settings is not None, "#946 指纹路径创建 chromadb 客户端必须显式传 settings"
        assert settings.anonymized_telemetry is False, "#946 匿名遥测必须关闭"


class TestRealClientTelemetryDisabled:
    """R3/R4 — 真实 chroma 客户端生效终判据（默认 True → 未修复必 FAIL）。"""

    async def test_r3_real_client_entity_path_telemetry_off(self, tmp_path: Path) -> None:
        """实体路径建出的真实客户端 get_settings() 必须为 False（关闭生效）。"""
        store = _store(tmp_path, FakeEmbeddings())
        await store.index(_entity())
        client = store._client
        assert client is not None, "索引后应已创建 chromadb 客户端"
        assert client.get_settings().anonymized_telemetry is False, (
            "#946 真实客户端 settings 未关闭匿名遥测（数据仍会上报）"
        )

    async def test_r4_real_client_meta_path_telemetry_off(self, tmp_path: Path) -> None:
        """指纹路径建出的真实客户端 get_settings() 必须为 False（关闭生效）。"""
        store = _store(tmp_path, FakeEmbeddings())
        await store.read_fingerprint(PROJECT)
        client = store._client
        assert client is not None, "读取指纹后应已创建 chromadb 客户端"
        assert client.get_settings().anonymized_telemetry is False, (
            "#946 指纹路径真实客户端 settings 未关闭匿名遥测"
        )


class TestTelemetryOffDoesNotBreakVectorStore:
    """【G】守护：关闭遥测不得改变懒加载与读写主路径。"""

    def test_g1_client_still_lazy(self, tmp_path: Path) -> None:
        """构造期不得创建 chromadb 客户端（懒加载语义不变）。"""
        store = _store(tmp_path, FakeEmbeddings())
        assert store._client is None

    async def test_g2_index_retrieve_roundtrip(self, tmp_path: Path) -> None:
        """传 settings 后真实读写主路径仍可用（index → retrieve 命中同一条）。"""
        store = _store(tmp_path, FakeEmbeddings())
        await store.index(_entity())
        hits = await store.retrieve("蜀山", project_id=PROJECT)
        assert [hit.entity_id for hit in hits] == ["e-946"]

    async def test_g3_second_store_same_dir_shares_settings(self, tmp_path: Path) -> None:
        """同目录二次建店（重装配/refresh 场景）不得因 settings 不一致崩。

        chromadb ``SharedSystemClient`` 按持久化目录**进程级**缓存 system：同目录
        二次创建客户端时 settings 必须完全相等，否则 ``ValueError: ... with
        different settings``（#946 落地实测的回归面——所有创建路径必须走同一设置）。
        """
        first = _store(tmp_path, FakeEmbeddings())
        await first.index(_entity())
        second = _store(tmp_path, FakeEmbeddings())
        hits = await second.retrieve("蜀山", project_id=PROJECT)
        assert [hit.entity_id for hit in hits] == ["e-946"]
