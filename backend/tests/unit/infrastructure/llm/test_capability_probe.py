"""F59-M2 RED (#963): 能力探测三级链 + 超能力软降级剥离（spec §5.4/§5.5）。

契约:
1. ``infrastructure/llm/capability_probe.py``（新文件）导出:
   - ``supports_reasoning_for_model(model_full, manual=None) -> bool``
     三级链（§5.4）：手动覆盖（True/False）> litellm.supports_reasoning(全名)
     > get_supported_openai_params 含 thinking/reasoning_effort；仅返回 bool，
     不泄漏 litellm 类型。
   - ``apply_reasoning_effort(kwargs, *, model_full, effort, manual=None) -> dict``
     构造点统一入口（§5.2/§5.5）:
     * effort None/"default" → kwargs 不加 reasoning_effort 键（不发参数，等价现状）
     * 能力支持 → kwargs["reasoning_effort"]=effort（含 "none" 透传，N-1 裁定：
       none 显式关闭依赖 litellm 翻译，不剥离）
     * 能力不支持 + effort ∉ {"default","none"} → **软降级**：剥离不注入 +
       loguru WARNING（log_structured，message_key="log.check.reasoning_downgrade"，
       params 含 model/effort），不断流不 422（Q1 拍板 A / §5.5）
     * 能力不支持 + effort=="none" → 透传（§5.5 行 2 恒思考不可关类，由
       litellm/provider 处理，§7.3 既有错误映射）
2. 探测内部异常（未知 provider/模型抛错）→ 兜底 False，绝不冒泡（N-2：
   GET /provider-configs 装配点逐条计算不得打崩）。
3. litellm import 仅允许 infrastructure（§5.6）——本测试以 patch 模块属性驱动，
   domain 层测试见 test_reasoning_model（零 litellm 锁）。

RED 预期失败形态:
- ``inkflow.infrastructure.llm.capability_probe`` 不存在 → 收集期 ModuleNotFoundError。
"""

from __future__ import annotations

import sys

import pytest

from inkflow.infrastructure.llm.capability_probe import (
    apply_reasoning_effort,
    supports_reasoning_for_model,
)

PROBE_MOD = "inkflow.infrastructure.llm.capability_probe"


@pytest.fixture
def loguru_records():
    """loguru 捕获 sink（test_logging_checkpoints._capture_records 同款形态）。"""
    from loguru import logger

    records: list[dict] = []
    sink_id = logger.add(
        lambda m: records.append(m.record), level="WARNING", format="{message}"
    )
    yield records
    logger.remove(sink_id)


def _warn_records(records: list[dict]) -> list[dict]:
    return [r for r in records if r["level"].name == "WARNING"]


class TestManualOverride:
    """§5.4 级 1：注册表 models[].supports_reasoning 手动值短路自动探测。"""

    def test_manual_true_skips_litellm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import litellm

        def _boom(*_a, **_k):
            raise AssertionError("手动覆盖为 True 时不得调用 litellm.supports_reasoning")

        monkeypatch.setattr(litellm, "supports_reasoning", _boom)
        assert supports_reasoning_for_model("glm-4.5", "zai", manual=True) is True

    def test_manual_false_skips_litellm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import litellm

        def _boom(*_a, **_k):
            raise AssertionError("手动覆盖为 False 时不得调用 litellm.supports_reasoning")

        monkeypatch.setattr(litellm, "supports_reasoning", _boom)
        assert supports_reasoning_for_model("deepseek/deepseek-v4-flash", manual=False) is False


class TestLitellmModelTable:
    """§5.4 级 2：litellm.supports_reasoning(全名)（模型级本地表，无网络 IO）。"""

    def test_deepseek_v4_flash_true(self) -> None:
        """M1 实证锚：litellm 1.99 supports_reasoning(deepseek/deepseek-v4-flash)=True。"""
        assert supports_reasoning_for_model("deepseek/deepseek-v4-flash") is True

    def test_true_short_circuits_level3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import litellm

        def _boom(*_a, **_k):
            raise AssertionError("级 2 命中 True 时不得进入 get_supported_openai_params")

        monkeypatch.setattr(litellm, "get_supported_openai_params", _boom)
        assert supports_reasoning_for_model("deepseek/deepseek-v4-flash") is True


class TestProviderParamsFallback:
    """§5.4 级 3：模型表 False → get_supported_openai_params 含 thinking/reasoning_effort。

    M1 实证素材：get_supported_openai_params("glm-4.5","zai") 不含 reasoning 参数
    （→ 最终 False）；本类用 monkeypatch 构造 provider 级 True 形态。
    """

    def test_glm45_zai_false(self) -> None:
        """实证回归锁：zai/glm-4.5 两级探测均无 → False（软降级用例的数据源）。"""
        assert supports_reasoning_for_model("zai/glm-4.5") is False

    def test_provider_params_contains_reasoning_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import litellm

        monkeypatch.setattr(litellm, "supports_reasoning", lambda *_a, **_k: False)
        monkeypatch.setattr(
            litellm,
            "get_supported_openai_params",
            lambda *_a, **_k: ["model", "messages", "reasoning_effort"],
        )
        assert supports_reasoning_for_model("some/model") is True

    def test_provider_params_contains_thinking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import litellm

        monkeypatch.setattr(litellm, "supports_reasoning", lambda *_a, **_k: False)
        monkeypatch.setattr(
            litellm,
            "get_supported_openai_params",
            lambda *_a, **_k: ["model", "thinking"],
        )
        assert supports_reasoning_for_model("some/model") is True

    def test_provider_params_without_keys_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import litellm

        monkeypatch.setattr(litellm, "supports_reasoning", lambda *_a, **_k: False)
        monkeypatch.setattr(
            litellm,
            "get_supported_openai_params",
            lambda *_a, **_k: ["model", "temperature"],
        )
        assert supports_reasoning_for_model("some/model") is False


class TestProbeNeverRaises:
    """N-2：探测内部任何异常 → False 兜底（不打崩 provider-configs 装配）。"""

    def test_supports_reasoning_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import litellm

        def _boom(*_a, **_k):
            raise RuntimeError("litellm table explode")

        monkeypatch.setattr(litellm, "supports_reasoning", _boom)
        assert supports_reasoning_for_model("weird/model") is False

    def test_params_lookup_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import litellm

        monkeypatch.setattr(litellm, "supports_reasoning", lambda *_a, **_k: False)

        def _boom(*_a, **_k):
            raise KeyError("unknown provider")

        monkeypatch.setattr(litellm, "get_supported_openai_params", _boom)
        assert supports_reasoning_for_model("weird/model") is False


class TestApplyReasoningEffort:
    """§5.2 不发规则 + §5.5 软降级剥离。"""

    def test_none_effort_not_injected(self) -> None:
        """未配置档位 → kwargs 完全不加 reasoning_effort 键（等价现状）。"""
        out = apply_reasoning_effort(
            {"model": "deepseek/deepseek-v4-flash"},
            model_full="deepseek/deepseek-v4-flash",
            effort=None,
        )
        assert "reasoning_effort" not in out

    def test_default_effort_not_injected(self) -> None:
        """🔴 spec §5.2：解析终点 "default" → 不发任何思考参数（M2 验收项）。"""
        out = apply_reasoning_effort(
            {"model": "deepseek/deepseek-v4-flash"},
            model_full="deepseek/deepseek-v4-flash",
            effort="default",
        )
        assert "reasoning_effort" not in out

    def test_supported_model_injects(self) -> None:
        out = apply_reasoning_effort(
            {"model": "deepseek/deepseek-v4-flash"},
            model_full="deepseek/deepseek-v4-flash",
            effort="high",
        )
        assert out["reasoning_effort"] == "high"

    def test_unsupported_downgrades_and_warns(
        self, loguru_records: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """软降级（Q1=A）：zai/glm-4.5 传 high → 剥离 + WARNING，不断流。"""
        out = apply_reasoning_effort(
            {"model": "zai/glm-4.5"},
            model_full="zai/glm-4.5",
            effort="high",
        )
        assert "reasoning_effort" not in out
        warns = _warn_records(loguru_records)
        assert warns, "软降级必须发 WARNING（不断流但必须留痕）"
        extra = warns[-1]["extra"]
        assert extra.get("message_key") == "log.check.reasoning_downgrade"
        params = extra.get("params") or {}
        assert params.get("model") == "zai/glm-4.5"
        assert params.get("effort") == "high"

    def test_none_level_passthrough_unsupported(
        self, loguru_records: list[dict]
    ) -> None:
        """N-1：能力不支持 + effort="none" → 显式关闭请求透传（§5.5 行 2 恒思考
        模型类由 provider 处理，§7.3 既有错误映射兜底）。"""
        out = apply_reasoning_effort(
            {"model": "zai/glm-4.5"},
            model_full="zai/glm-4.5",
            effort="none",
        )
        assert out.get("reasoning_effort") == "none"
        assert not _warn_records(loguru_records)

    def test_manual_true_rescues_injection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """注册表手动覆盖 True → 未知模型照常注入（§7 边界 #2 新模型通道）。"""
        out = apply_reasoning_effort(
            {"model": "brandnew/x1"},
            model_full="brandnew/x1",
            effort="medium",
            manual=True,
        )
        assert out["reasoning_effort"] == "medium"

    def test_returns_new_dict_not_mutating(self) -> None:
        base = {"model": "deepseek/deepseek-v4-flash"}
        out = apply_reasoning_effort(base, model_full="deepseek/deepseek-v4-flash", effort="low")
        assert out is not base
        assert "reasoning_effort" not in base  # 原 dict 不被就地修改

    def test_module_isolated_for_cli_import(self) -> None:
        """护栏：capability_probe 模块自身 import 不拉入 FastAPI（装配注入用）。"""
        mod = sys.modules[PROBE_MOD]
        src = __import__("inspect").getsource(mod)
        assert "fastapi" not in src


class TestChatLiteLLMCtorWiring:
    """构造点接线（§5.2 + §8.1 test_litellm_migration 同款形态的最小锚）：
    _get_chat_model 收到 reasoning_effort 后必须经 apply_reasoning_effort 进
    ChatLiteLLM kwargs；default/None 不发。"""

    def _call(self, **kw):
        from unittest.mock import MagicMock, patch

        from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
        from inkflow.infrastructure.llm.provider_config import LLMProviderConfig

        cfg = LLMProviderConfig(
            provider="deepseek",
            api_key="k",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-v4-flash",
            max_retries=3,
            timeout=30,
        )
        with patch("inkflow.infrastructure.llm.langchain_client.ChatLiteLLM") as mock_cls:
            mock_cls.return_value = MagicMock(name="chat")
            LangChainLLMClient()._get_chat_model(cfg, **kw)
        return mock_cls.call_args[1]

    def test_high_injects_kwarg(self) -> None:
        """#1044 D1：注入必须走 model_kwargs（顶层键被 ChatLiteLLM pydantic 丢弃）。"""
        kwargs = self._call(model_name="deepseek-v4-flash", reasoning_effort="high")
        assert kwargs["model_kwargs"]["reasoning_effort"] == "high"
        assert "reasoning_effort" not in kwargs, (
            "顶层 reasoning_effort 被 ChatLiteLLM 静默丢弃（#1044 D1），不得再发"
        )

    def test_default_omits_kwarg(self) -> None:
        kwargs = self._call(model_name="deepseek-v4-flash", reasoning_effort="default")
        assert "model_kwargs" not in kwargs
        assert "reasoning_effort" not in kwargs

    def test_absent_omits_kwarg(self) -> None:
        kwargs = self._call(model_name="deepseek-v4-flash")
        assert "model_kwargs" not in kwargs
        assert "reasoning_effort" not in kwargs


class TestTranslatorGateDecision:
    """#1044 D4：探测链判 True 但 litellm 翻译器无参数 → 决策点软降级（不注入）。

    实证（litellm 1.99 + langchain-litellm 0.7.1）：
    - ``supports_reasoning("dashscope/qwen3-max")`` = True，但
      ``get_supported_openai_params("qwen3-max", "dashscope")`` 无
      reasoning_effort/thinking → 注入即 SDK 本地 ``UnsupportedParamsError``（断流）。
    - ``none`` 档同样必炸（SDK 校验不看值），必须一并剥离。
    """

    def test_dashscope_probe_true_but_gate_strips(self, loguru_records: list[dict]) -> None:
        assert supports_reasoning_for_model("dashscope/qwen3-max") is True, (
            "本用例前提：探测链判 True（D4 的矛盾面）"
        )
        out = apply_reasoning_effort(
            {"model": "dashscope/qwen3-max"},
            model_full="dashscope/qwen3-max",
            effort="high",
        )
        assert "reasoning_effort" not in out
        warns = _warn_records(loguru_records)
        assert warns, "翻译器无参数必须软降级留痕（WARNING）"
        extra = warns[-1]["extra"]
        assert extra.get("message_key") == "log.check.reasoning_downgrade"
        params = extra.get("params") or {}
        assert params.get("reason") == "translator_unsupported"
        assert params.get("model") == "dashscope/qwen3-max"

    def test_dashscope_none_also_stripped(self, loguru_records: list[dict]) -> None:
        """none 档也送不出去：翻译器无该参数时 SDK 一律 UnsupportedParamsError。"""
        out = apply_reasoning_effort(
            {"model": "dashscope/qwen3-max"},
            model_full="dashscope/qwen3-max",
            effort="none",
        )
        assert "reasoning_effort" not in out
        assert _warn_records(loguru_records)

    def test_deepseek_gate_passes(self, loguru_records: list[dict]) -> None:
        """主路径回归锁：deepseek 翻译器含 reasoning_effort → 照常注入、无告警。"""
        out = apply_reasoning_effort(
            {"model": "deepseek/deepseek-v4-flash"},
            model_full="deepseek/deepseek-v4-flash",
            effort="high",
        )
        assert out["reasoning_effort"] == "high"
        assert not _warn_records(loguru_records)

    def test_gate_lookup_exception_soft_degrades(
        self, loguru_records: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """翻译器查询异常 → 剥离 + WARNING（绝不冒泡、绝不断流）。"""
        import litellm

        monkeypatch.setattr(litellm, "supports_reasoning", lambda *_a, **_k: True)

        def _boom(*_a: object, **_k: object) -> list[str]:
            raise RuntimeError("translator table explode")

        monkeypatch.setattr(litellm, "get_supported_openai_params", _boom)
        out = apply_reasoning_effort(
            {"model": "some/model"}, model_full="some/model", effort="high"
        )
        assert "reasoning_effort" not in out
        warns = _warn_records(loguru_records)
        assert warns
        assert (warns[-1]["extra"].get("params") or {}).get("reason") == (
            "translator_unsupported"
        )

    def test_manual_override_exempt_from_translator_gate(
        self, loguru_records: list[dict]
    ) -> None:
        """§7 边界 #2 新模型通道：manual=True 是用户显式断言，不受翻译器门禁约束。

        生产两构造点不传 manual（仅注册表回显用），故 D4 主链路仍受门禁保护。
        """
        out = apply_reasoning_effort(
            {"model": "brandnew/x1"},
            model_full="brandnew/x1",
            effort="high",
            manual=True,
        )
        assert out["reasoning_effort"] == "high"
        assert not _warn_records(loguru_records)


class TestTransportAdapter:
    """#1044 D1：决策 dict → ChatLiteLLM 构造 kwargs（reasoning_effort 搬进 model_kwargs）。"""

    def test_moves_effort_into_model_kwargs(self) -> None:
        from inkflow.infrastructure.llm.capability_probe import to_chat_model_kwargs

        out = to_chat_model_kwargs({"model": "m", "reasoning_effort": "high"})
        assert out["model_kwargs"] == {"reasoning_effort": "high"}
        assert "reasoning_effort" not in out

    def test_no_effort_key_is_noop(self) -> None:
        from inkflow.infrastructure.llm.capability_probe import to_chat_model_kwargs

        out = to_chat_model_kwargs({"model": "m"})
        assert out == {"model": "m"}
        assert "model_kwargs" not in out

    def test_merges_existing_model_kwargs(self) -> None:
        from inkflow.infrastructure.llm.capability_probe import to_chat_model_kwargs

        out = to_chat_model_kwargs(
            {
                "model": "m",
                "model_kwargs": {"extra_body": {"x": 1}},
                "reasoning_effort": "none",
            }
        )
        assert out["model_kwargs"] == {
            "extra_body": {"x": 1},
            "reasoning_effort": "none",
        }

    def test_does_not_mutate_input(self) -> None:
        from inkflow.infrastructure.llm.capability_probe import to_chat_model_kwargs

        base = {"model": "m", "reasoning_effort": "high"}
        out = to_chat_model_kwargs(base)
        assert out is not base
        assert base == {"model": "m", "reasoning_effort": "high"}
