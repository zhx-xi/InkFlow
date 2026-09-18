"""#1280 RED 契约：审计装配在「无模型可解析」时必须降级（200 + degraded），不得 422.

## 事故链（实证）

e2e `e2e-audit.spec.ts:139/:186` 两用例确定性失败：审计弹窗显示
「审计失败｜未配置默认模型，请在设置中配置 LLM Provider 和默认模型」
而非审计报告。

| 环节 | 实证 |
|---|---|
| 隔离数据目录无 `config.json` | `config.llm_default_model == ""`（`config.py:290` 默认空） |
| `ensureModelConfigured` 只配注册表 + key | **不写**全局默认模型，也**不写**项目级 model |
| 审计端点装配期抛 422 | `deps_chapter_audit.py:67` → `_llm_resolver.py:46` |
| 前端展示错误态 | `AuditDialog.tsx:102` `!report && error` → 错误标题 + 文案 |

## 与 #1269 / #1272 的关系

**同根因族（A）**：#1269 是「隔离目录无全局模型 → 裸构造客户端 →
`parse_model_string("")` 抛 ValueError → 恒降级」。#1272 修了「项目级 model
不被消费」，但**顺手把「全空」从「静默降级」改成了「装配期硬 422」**——
这一步**越过了 F34 契约**。

## 契约冲突（本 issue 的核心）

| 来源 | 对「无模型/LLM 不可用」的主张 |
|---|---|
| F34 spec §3.3 错误表 | `LLM 分析失败 → 200 + degraded`，**「不视为 HTTP 错误」** |
| F34 spec §5.3 / D2 / M4 | 降级不阻塞：确定性检查照常返回，`degraded=true` |
| F34 spec §3.3 注 | **「API 错误面只有 404/422」**（404=不存在；422=confirm/DTO） |
| `e2e-audit.spec.ts:12/:158` | 「无 LLM key：LLM 检查降级 → 报告 degraded 标记，确定性检查返回」 |
| #1269 单测（原 `..._raises_422_...`） | 422「绝不静默降级」← **与 spec 冲突（本 PR 翻转）** |

⇒ 「无模型」是 **LLM 分析失败** 的一种形态 → 必须 200 + degraded。
本文件把该契约钉死；`#1269` 冲突断言已同步翻转为 spec 口径（见该文件断言 2）。

## 本文件断言（缺陷态必 FAIL）

1. **装配不抛 422**：全局空 + 项目级空 → `get_chapter_audit_service(..., resolve_credentials=True)`
   **正常返回服务**（不抛 HTTPException）。
2. **不造出「假可用」客户端**：返回的客户端在 `chat()` 时必须**失败**（而非静默发空模型请求
   或返回假响应）——保证降级由 §5.3 既有路径承接（`_run_drift_check` → `([], True)`）。
3. **降级可诊断**：装配期落 WARNING/ERROR 日志（保留 #1269 §4.1 的可诊断性成果）。
4. **端到端语义**：注入该降级客户端跑 `_run_drift_check` → `([], True)`，**绝不抛出**
   （spec §5.3：HTTP 200 语义）。
5. **可证伪**：模型**可解析**时不得走降级（客户端正常持模型）——防「一律降级」的恒真退化。

依据: issue #1280；spec §3.3 / §5.3 / D2 / M4 / E5；#1269 §4.1；#1272 PR 正文。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── 断言 1/2/3/5：deps 层「无解不 422」─────────────────────────────────


class TestAuditDepsNoModelDegradesNot422:
    """#1280：模型全空是「LLM 分析失败」→ 装配降级，绝不 422（spec §3.3/§5.3）。"""

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_no_model_does_not_raise_422(
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
        """断言 1：全局空 + 项目级空 → 正常返回服务（不抛 422）。

        缺陷态：`resolve_chat_model("")` 抛 HTTPException(422) → 本断言 FAIL。
        spec §3.3：LLM 分析失败「不视为 HTTP 错误」；错误面只有 404/422（confirm/DTO）。
        """
        from inkflow.api.deps import get_chapter_audit_service

        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_audit_svc.return_value = MagicMock()
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        svc = get_chapter_audit_service(MagicMock(), project_model=None, resolve_credentials=True)

        assert svc is not None, (
            "#1280：无模型可解析属「LLM 分析失败」→ 必须装配出服务并降级（200 + degraded），"
            "不得以 422 让整个审计端点失败（spec §3.3 / §5.3）"
        )

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    @pytest.mark.asyncio
    async def test_degraded_client_fails_on_chat_not_silently_succeeds(
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
        """断言 2：降级客户端在 `chat()` 必失败 —— 绝不静默发空模型请求/返回假响应。

        这是 #1269「绝不静默造出空模型客户端」**意图的忠实保留**：
        客户端的「空」必须表现为**可捕获的失败**（→ §5.3 降级），而不是「看起来能用」。
        """
        from inkflow.api.deps import get_chapter_audit_service
        from inkflow.domain.ports.llm_client import ChatMessage

        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_audit_svc.return_value = MagicMock()
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        svc = get_chapter_audit_service(MagicMock(), project_model=None, resolve_credentials=True)
        msgs = [
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content="u"),
        ]
        with pytest.raises(Exception) as exc:
            await svc._llm.chat(msgs)

        assert str(exc.value), (
            "#1280：无模型客户端 chat() 必须抛出（带诊断消息）→ 由 §5.3 降级路径承接；"
            "静默成功会产出假报告（比 422 更危险）"
        )

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_no_model_logs_diagnostic(
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
        """断言 3：装配降级必须落含诊断信息的日志（保留 #1269 §4.1 成果）。

        loguru 不走 stdlib logging → 用 loguru 自身 sink 捕获。
        """
        from loguru import logger as _lg

        from inkflow.api.deps import get_chapter_audit_service

        m_config.llm_default_model = ""
        m_config.model_routing = {}
        m_audit_svc.return_value = MagicMock()
        m_get_provider.side_effect = ValueError("API key not configured for provider")

        captured: list[str] = []
        sink_id = _lg.add(lambda m: captured.append(str(m)), level="WARNING")
        try:
            get_chapter_audit_service(MagicMock(), project_model=None, resolve_credentials=True)
        finally:
            _lg.remove(sink_id)

        joined = " ".join(captured)
        assert "LLM" in joined or "model" in joined.lower(), (
            "#1280/#1269 §4.1：装配降级必须落诊断日志（project_model/global 空 + 可操作提示），"
            f"否则「审计失败且原因不可见」重演。实际捕获={captured!r}"
        )

    @patch("inkflow.api.deps.SQLiteAuditLogRepository")
    @patch("inkflow.api.deps.SQLiteWorldRepository")
    @patch("inkflow.api.deps.SQLiteCharacterRepository")
    @patch("inkflow.api.deps.SQLiteChapterRepository")
    @patch("inkflow.api.deps.SQLiteProjectRepository")
    @patch("inkflow.api.deps.get_audit_service")
    @patch("inkflow.infrastructure.llm.provider_config.get_provider_config")
    @patch("inkflow.core.config.config")
    def test_resolvable_model_does_not_degrade(
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
        """断言 5（可证伪）：模型可解析时**不得**走降级客户端 —— 防「一律降级」恒真退化。

        `get_provider_config` 正常返回且项目级 model 非空 → 客户端必须持该模型。
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
            MagicMock(), project_model="deepseek/deepseek-flash", resolve_credentials=True
        )

        assert getattr(svc._llm, "_default_model", "") == "deepseek/deepseek-flash", (
            "#1280 可证伪：模型可解析却走了降级 → 修复过度（把正常路径也降级了）"
        )


# ── 断言 4：端到端语义（降级不抛出，spec §5.3）─────────────────────────


class TestNoModelEndToEndDegrades:
    """#1280：无模型客户端注入审计服务 → `_run_drift_check` 返回 ([], True)，绝不抛出。"""

    @pytest.mark.asyncio
    async def test_degraded_client_yields_degrade_not_raise(self) -> None:
        """断言 4：真实 `LangChainLLMClient`（空模型）→ §5.3 降级路径承接。"""
        from inkflow.core.config import config
        from inkflow.domain.ports.llm_client import ChatMessage
        from inkflow.domain.services.chapter_audit_service import ChapterAuditService
        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

        with patch.object(config, "llm_default_model", ""):
            client = LangChainLLMClient(default_model="")

        svc = ChapterAuditService(
            project_repo=MagicMock(),
            chapter_repo=MagicMock(),
            character_repo=MagicMock(),
            world_repo=MagicMock(),
            audit_service=MagicMock(),
            llm_client=client,
            audit_log_repo=MagicMock(),
        )
        msgs = [
            ChatMessage(role="system", content="s"),
            ChatMessage(role="user", content="u"),
        ]

        findings, degraded = await svc._run_drift_check(msgs)

        assert findings == [] and degraded is True, (
            "#1280：无模型 → LLM 检查降级（spec §5.3），HTTP 仍 200 + 确定性检查照常返回。"
            "e2e `e2e-audit.spec.ts:158` 即断言此契约"
        )
