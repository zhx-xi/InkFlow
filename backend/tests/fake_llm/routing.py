"""fake LLM 请求路由（S0，ADR-047）：根据 model / payload 签名选择确定性 fixture。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Fixture:
    kind: str  # "correct" | "error" | "timeout" | "malformed" | "empty"
    status_code: int  # 200 for correct，4xx/5xx for error
    content: str = ""  # 正常场景的 assistant content（error 场景为空）
    error_code: str | None = None  # e.g. "rate_limit_exceeded" / "unauthorized" / "server_error"
    error_message: str | None = None
    delay_seconds: float = 0.0  # timeout 场景 > 0
    tool_calls: list | None = None


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(scene: str) -> dict:
    """从 fixtures JSON 读取场景数据；文件缺失/解析失败返回空 dict（用硬编码默认兜底）。"""
    path = _FIXTURE_DIR / ("correct/default.json" if scene == "correct" else f"error/{scene}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_SCENARIO_DEFAULTS: dict[str, Fixture] = {
    "correct": Fixture(kind="correct", status_code=200, content="这是确定性 fake 响应"),
    "error-401": Fixture(
        kind="error", status_code=401, error_code="unauthorized", error_message="Invalid API key"
    ),
    "error-429": Fixture(
        kind="error",
        status_code=429,
        error_code="rate_limit_exceeded",
        error_message="Rate limit exceeded",
    ),
    "error-500": Fixture(
        kind="error",
        status_code=500,
        error_code="server_error",
        error_message="Internal server error",
    ),
    "error-timeout": Fixture(kind="timeout", status_code=503, delay_seconds=2.0),
    "empty": Fixture(kind="empty", status_code=200, content=""),
    "malformed": Fixture(kind="malformed", status_code=200, content="not-json"),
}


def _scenario_fixture(scene: str) -> Fixture:
    """按场景名构造 Fixture：JSON 数据（只取该场景对应字段）优先，硬编码默认兜底。"""
    data = _load_fixture(scene)
    base = _SCENARIO_DEFAULTS.get(scene, _SCENARIO_DEFAULTS["correct"])
    if not data:
        return base
    return Fixture(
        kind=str(data.get("kind", base.kind)),
        status_code=int(data.get("status_code", base.status_code)),
        content=str(data.get("content", base.content)),
        error_code=data.get("error_code", base.error_code),
        error_message=data.get("error_message", base.error_message),
        delay_seconds=float(data.get("delay_seconds", base.delay_seconds)),
        tool_calls=data.get("tool_calls", base.tool_calls),
    )


def _resolve_scene(model: str, payload: dict) -> str:
    """签名优先：payload 任一 message 的 content 含 `[[fake-scenario:<scene>]]` 则取 scene；
    否则取 model 中 '/' 后的后缀。未知场景保持原值，由上层默认兜底。"""
    pattern = re.compile(r"\[\[fake-scenario:([\w-]+)\]\]")
    for msg in payload.get("messages", []):
        if not isinstance(msg, dict):
            continue
        match = pattern.search(str(msg.get("content", "")))
        if match:
            return match.group(1)
    return model.rsplit("/", 1)[-1] if "/" in model else model


def select_fixture(model: str, payload: dict) -> Fixture:
    """选择 fixture：payload 签名覆盖 model 路由；未知 model 返回默认 correct（不崩溃）。"""
    scene = _resolve_scene(model, payload)
    return _scenario_fixture(scene)
