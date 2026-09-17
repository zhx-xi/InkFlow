"""#1269 RED 契约：审计链模型解析 + 降级可诊断性（打包产物恒 degraded 缺陷）。

## 缺陷背景（实证）

打包产物（隔离数据目录，无全局模型）下调用章节审计：

- `config.llm_default_model = ""`（隔离目录无 config.json / instance.env）
- 项目级 model 已配（`projects.config.model = "deepseek/deepseek-flash"`）**但审计链不读**
- `deps.get_chapter_audit_service` 用裸 `LangChainLLMClient()` →
  `_default_model = "" or config.llm_default_model` = `""`
- → `parse_model_string("")` 抛 `ValueError: Invalid model format: ''`
- → `chapter_audit_service.py:406 except Exception: return [], True` 静默吞掉
- → HTTP 200 + `degraded=True` + `findings=[]`（8/8 章）

实证（rc2 打包产物 + 隔离目录 D:\\tmp\\w10a-verify）：
`_chat_async started` @01:02:59.966 → `_chat_async failed` @01:02:59.969（同毫秒区间，3ms）
→ 前置校验立即抛错，非超时/网络。

## 本文件断言（当前必 FAIL）

1. **deps 层：项目级 model 被消费** —— 全局空 + 项目级 model 非空时，
   构造出的审计服务其 LLM 客户端 `_default_model` 必须等于项目级 model（非空）。
2. **deps 层：全局空 + 项目级空 → 不再造出空模型客户端**（422 诊断，绝不静默降级）。
3. **服务层：降级落日志** —— 模型调用异常时除返回 `([], True)` 外，
   必须落一条含异常详情的 WARNING/ERROR 日志（可诊断性，issue §4.1）。
4. **可证伪**：显式传空 model → 断言 1 必须 FAIL（防恒真断言）。

依据: issue #1269 §2/§4；spec §5.3（降级语义不变，HTTP 200）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 断言 1/2：deps 层模型解析 ────────────────────────────────────────────


class TestChapterAuditDepsModelResolution:
    """#1269：审计服务构造必须消费项目级/全局模型，不得裸构造空模型客户端。"""

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_project_model_is_consumed_when_global_empty(
        self,
        m_config,
        m_get_provider,
        m_audit_svc,
        _p_repo,
        _c_repo,
        _ch_repo,
        _w_repo,
        _log_repo,
    ) -> None:
        """断言 1：全局空 + 项目级 model → 客户端 `_default_model` == 项目级 model。

        当前实现裸构造 `LangChainLLMClient()` → `_default_model` 为 "" → FAIL。
        """
        from inkflow.api.deps import get_chapter_audit_service
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        m_config.llm_default_model = ""  # 隔离目录形态：无全局模型
        m_audit_svc.return_value = MagicMock()
        m_get_provider.return_value = LLMProviderConfig(
            provider="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek/deepseek-flash",
            models=["deepseek-flash"],
        )

        svc = get_chapter_audit_service(
            MagicMock(), project_model="deepseek/deepseek-flash", resolve_credentials=True
        )

        client = svc._llm
        assert getattr(client, "_default_model", "") == "deepseek/deepseek-flash", (
            "#1269：审计客户端必须持有项目级 model —— 空值会让 parse_model_string('') "
            "立即抛 ValueError → 恒降级（打包产物 8/8 章 degraded 根因）"
        )

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_global_model_used_when_project_model_absent(
        self,
        m_config,
        m_get_provider,
        m_audit_svc,
        _p_repo,
        _c_repo,
        _ch_repo,
        _w_repo,
        _log_repo,
    ) -> None:
        """断言 1b：项目级缺 → 回落全局默认（不回归 dev/APPDATA 形态）。"""
        from inkflow.api.deps import get_chapter_audit_service
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        m_config.llm_default_model = "deepseek/deepseek-v4-flash"
        m_audit_svc.return_value = MagicMock()
        m_get_provider.return_value = LLMProviderConfig(
            provider="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek/deepseek-v4-flash",
            models=["deepseek-v4-flash"],
        )

        svc = get_chapter_audit_service(MagicMock(), project_model=None, resolve_credentials=True)
        assert getattr(svc._llm, "_default_model", "") == "deepseek/deepseek-v4-flash"

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_empty_both_raises_422_not_silent_client(
        self,
        m_config,
        m_get_provider,
        m_audit_svc,
        _p_repo,
        _c_repo,
        _ch_repo,
        _w_repo,
        _log_repo,
    ) -> None:
        """断言 2：全局空 + 项目级空 → 422 诊断，绝不造出空模型客户端。

        当前实现直接返回一个 `_default_model == ""` 的服务（静默）→ FAIL。
        """
        from fastapi import HTTPException

        from inkflow.api.deps import get_chapter_audit_service

        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_audit_svc.return_value = MagicMock()
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        with pytest.raises(HTTPException) as exc:
            get_chapter_audit_service(MagicMock(), project_model=None, resolve_credentials=True)

        assert exc.value.status_code == 422
        assert "默认模型" in exc.value.detail or "model" in exc.value.detail.lower()

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_project_model_actually_drives_client_model(
        self,
        m_config,
        m_get_provider,
        m_audit_svc,
        _p_repo,
        _c_repo,
        _ch_repo,
        _w_repo,
        _log_repo,
    ) -> None:
        """可证伪自证：把「项目级 model」换成另一个值 → 客户端模型必须随之改变。

        若客户端模型恒定（与入参无关），说明断言 1 是同源恒真断言（复刻实现字面量）。
        """
        from inkflow.api.deps import get_chapter_audit_service
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        m_config.llm_default_model = ""
        m_audit_svc.return_value = MagicMock()
        m_get_provider.return_value = LLMProviderConfig(
            provider="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek/deepseek-flash",
            models=["deepseek-flash"],
        )

        svc = get_chapter_audit_service(
            MagicMock(), project_model="zhipu/glm-4", resolve_credentials=True
        )
        got = getattr(svc._llm, "_default_model", "")
        assert got == "zhipu/glm-4", (
            f"可证伪失败：客户端模型 {got!r} 不随 project_model 变化 → 断言 1 未真正承重"
        )


# ── 断言 3：降级落日志（可诊断性，issue §4.1）───────────────────────────


class TestDriftCheckDegradeLogging:
    """#1269 §4.1：降级时必须落含异常详情的日志（保持 degraded 语义不变）。"""

    @pytest.mark.asyncio
    async def test_degrade_logs_exception_detail(self) -> None:
        """断言 3：chat 抛异常 → 仍返回 ([], True)，且日志含异常类型/消息。

        loguru 不走 stdlib logging → caplog 捕不到；用 loguru 自身 sink 捕获。
        """
        from loguru import logger as _lg

        from inkflow.domain.ports.llm_client import ChatMessage
        from inkflow.domain.services.chapter_audit_service import ChapterAuditService

        llm = MagicMock()
        llm.chat = AsyncMock(
            side_effect=ValueError("Invalid model format: ''. Expected 'provider/model_name'.")
        )
        svc = ChapterAuditService(
            project_repo=MagicMock(),
            chapter_repo=MagicMock(),
            character_repo=MagicMock(),
            world_repo=MagicMock(),
            audit_service=MagicMock(),
            llm_client=llm,
            audit_log_repo=MagicMock(),
        )
        msgs = [
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content="u"),
        ]
        captured: list[str] = []
        sink_id = _lg.add(lambda m: captured.append(str(m)), level="WARNING")
        try:
            findings, degraded = await svc._run_drift_check(msgs)
        finally:
            _lg.remove(sink_id)

        assert findings == [] and degraded is True, "降级语义不变（spec §5.3）"
        joined = " ".join(captured)
        assert "Invalid model format" in joined or "ValueError" in joined, (
            "#1269 §4.1：降级必须落含异常详情的日志，否则根因不可见（本 issue 排查困难之源）"
        )

    @pytest.mark.asyncio
    async def test_degrade_semantics_unchanged_no_raise(self) -> None:
        """断言 3b：降级绝不抛出（spec §5.3 首行，HTTP 200 语义）。"""
        from inkflow.domain.ports.llm_client import ChatMessage
        from inkflow.domain.services.chapter_audit_service import ChapterAuditService

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
        svc = ChapterAuditService(
            project_repo=MagicMock(),
            chapter_repo=MagicMock(),
            character_repo=MagicMock(),
            world_repo=MagicMock(),
            audit_service=MagicMock(),
            llm_client=llm,
            audit_log_repo=MagicMock(),
        )
        msgs = [
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content="u"),
        ]
        findings, degraded = await svc._run_drift_check(msgs)
        assert findings == []
        assert degraded is True


# ── 断言 4：可证伪 —— 裸客户端在空模型下必抛（根因机制钉住）─────────────


class TestBareClientEmptyModelRootCause:
    """钉住根因机制：空模型字符串 → parse_model_string 立即抛 ValueError。"""

    def test_parse_model_string_empty_raises(self) -> None:
        from inkflow.infrastructure.llm.provider_config import parse_model_string

        with pytest.raises(ValueError):
            parse_model_string("")

    def test_bare_client_default_model_is_empty_without_global(self) -> None:
        """裸构造 + 全局空 → `_default_model == ""`（缺陷机制的最小可证伪面）。"""
        from inkflow.core.config import config
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        with patch.object(config, "llm_default_model", ""):
            client = LangChainLLMClient()
        assert client._default_model == ""
