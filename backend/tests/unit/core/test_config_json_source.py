"""Issue #987：config.json 全局配置只写不读 — 启动源读回 RED 契约测试（方案 A）。

契约节（用户拍板方案 A 优先级）：init > 进程 env > instance.env > .env > config.json > secrets。

GREEN 义务（backend/src/inkflow/core/config.py）：
1. 新增 ConfigJsonSettingsSource（镜像 #977 _InstanceEnvSettingsSource 形态：继承
   EnvSettingsSource，覆写 _load_env_vars 读 {data_dir}/config.json），并入
   settings_customise_sources，位置在 dotenv_settings 之后、file_secret_settings 之前。
2. data_dir 定位序：init 构造参数 data_dir > 进程 env INKFLOW_DATA_DIR > _default_data_dir()
   （instance.env 锚点 / frozen / ./data）。data_dir 键本身不作为 config.json 启动字段
   （data-dir 走 instance.env，#266 语义，防鸡生蛋定位环）。
3. 键形映射：case_sensitive=False → 输出键为小写 "inkflow_<field>"（命中 env_prefix 匹配）。
   仅收 InkFlowConfig 已知字段键（model_fields，剔除 data_dir），未知键忽略。
4. 值归一：str 原样；bool → "true"/"false"；int/float → str()；dict/list → json.dumps()
   （复杂字段 JSON 解码语义与 env/instance.env 源一致）；值为 None/空串 → 跳过该键
   （镜像 load_instance_env 空值跳过语义，不遮挡默认值）。
5. 顶层非 dict JSON（如列表）→ 视为 {} 不抛异常（load_config_json 硬化：
   dict(_json.loads(...)) 对 [1,2] 抛 TypeError，启动源消费面必须兜住）。
6. debug 键：由源接管后 _derive_paths 的 validator 特判保留兼容（F51 D8 三连护栏零翻转，
   见 test_config_instance_env.py S3f 组 + 本文件 ie1-beats-jsonfalse 守护）。

RED 现状：config.json 不是任何启动源 → 【R】用例断言 FAIL（字段回空串/默认值）；
【G】守护用例现即 PASS，GREEN 后必须仍绿（防源插错序 / 键过滤缺失 / 值归一破坏）。

隔离纪律（镜像 test_config_instance_env.py）：instance.env 锚点一律 _patch_anchor 指
tmp_path（防本机真实 %APPDATA%/InkFlow/instance.env 注入）；用例触达的 INKFLOW_* 进程
env 键显式 delenv/setenv（防 conftest setdefault 与宿主环境污染）；.env 源用例
monkeypatch.chdir 至含 .env 的 tmp 目录（pydantic env_file=".env" 按 cwd 解析）。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from inkflow.core.config import (
    InkFlowConfig,
    save_config_json,
)

# inkflow.core 包把 config 属性重绑定为实例，用 importlib 取 sys.modules 中的真实模块
core_config_mod = importlib.import_module("inkflow.core.config")


def _patch_anchor(monkeypatch, anchor: Path) -> None:
    """把 config 模块的 get_instance_env_path 替换为固定锚点（测试隔离用）。

    镜像 test_config_instance_env.py:50 手法：raising=False 容忍属性缺失场景，
    GREEN 阶段覆盖真实函数，load_instance_env / 新源命中锚点。
    """
    monkeypatch.setattr(
        core_config_mod, "get_instance_env_path", lambda: anchor, raising=False
    )


def _empty_anchor(monkeypatch, tmp_path) -> Path:
    """锚点指向 tmp 下空 instance.env（隔离宿主真实锚点）。"""
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("", encoding="utf-8")
    return anchor


def _write_config_json(data_dir: Path, payload: object) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── 【R】A 组：config.json 并入启动源（GREEN 核心义务，issue #987 回归第 1 条）──
def test_config_json_llm_default_model_enters_config(monkeypatch, tmp_path) -> None:
    """#987-A1【R】config.json 含 llm_default_model + instance.env 无该键 →
    InkFlowConfig(data_dir=...) 非空 == 文件值。

    现实现 config.json 非启动源 → llm_default_model 仍为默认 "" → FAIL。
    GREEN 义务：ConfigJsonSettingsSource 并入（方案 A 优先级第 5 位）。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"llm_default_model": "deepseek/deepseek-v4-flash"})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.llm_default_model == "deepseek/deepseek-v4-flash"


def test_config_json_arbitrary_key_not_just_model(monkeypatch, tmp_path) -> None:
    """#987-A2【R】全键语义（不止 model）：config.json 含 server_port=8080 →
    InkFlowConfig().server_port == 8080。

    证明读回面向全部已知字段（CONFIG_WHITELIST 7 键映射字段无一例外），
    非 debug/单键特判。现实现仍为默认 8000 → FAIL。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_SERVER_PORT", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"server_port": 8080})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_port == 8080


def test_save_config_json_roundtrip_survives_restart(monkeypatch, tmp_path) -> None:
    """#987-A3【R】写读闭环（#735 D2 自动配置落盘值重启后仍在）：save_config_json
    写入 llm_default_model + llm_temperature → 重新构造（模拟内核重启）两字段均回读。

    现实现 save 落盘成功但重启后回空 → FAIL。GREEN 义务：写入端零改动，读取端并入源。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    save_config_json(data_dir, {"llm_default_model": "auto/deepseek-chat", "llm_temperature": 0.4})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.llm_default_model == "auto/deepseek-chat"
    assert settings.llm_temperature == 0.4


def test_config_json_complex_field_json_decoded(monkeypatch, tmp_path) -> None:
    """#987-A4【R】复杂字段值归一：config.json 含 model_routing dict → JSON 解码入字段
    （非 str() 字面量化）。

    GREEN 义务第 4 条：dict/list 值 json.dumps 后进源，复杂字段解码语义与 env 源一致。
    现实现默认 model_routing（openai=gpt-4o）≠ m1 → FAIL。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_MODEL_ROUTING", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(
        data_dir,
        {"model_routing": {"openai": {"model": "m1", "type": "chat"}}},
    )

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.model_routing["openai"].model == "m1"


# ── 【R】G 组：源内 data_dir 定位序（GREEN 义务第 2 条）──
def test_config_json_located_by_process_env_data_dir(monkeypatch, tmp_path) -> None:
    """#987-G1【R】进程 env INKFLOW_DATA_DIR 定位 config.json（无构造参数）→
    server_port 读回 8080。

    现实现非启动源 → 默认 8000 → FAIL。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_SERVER_PORT", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"server_port": 8080})
    monkeypatch.setenv("INKFLOW_DATA_DIR", str(data_dir))

    settings = InkFlowConfig()

    assert settings.server_port == 8080


def test_config_json_located_by_instance_env_data_dir(monkeypatch, tmp_path) -> None:
    """#987-G2【R】instance.env 锚点 INKFLOW_DATA_DIR 定位 config.json →
    server_port 读回 8080（_default_data_dir 链，frozen/dev 一致）。

    现实现非启动源 → 默认 8000 → FAIL。
    """
    anchor = _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_SERVER_PORT", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "persisted"
    _write_config_json(data_dir, {"server_port": 8080})
    anchor.write_text(f"INKFLOW_DATA_DIR={data_dir}\n", encoding="utf-8")

    settings = InkFlowConfig()

    assert settings.server_port == 8080


# ── 【R】E3：顶层非 dict JSON 不炸启动源（GREEN 义务第 5 条）──
def test_config_json_non_dict_toplevel_falls_back(monkeypatch, tmp_path) -> None:
    """#987-E3【R】config.json 顶层为 JSON 列表 → 视为 {} 走默认值，不抛异常。

    现实现 dict([1, 2]) 抛 TypeError 且 validator debug 分支会触发 → 构造 ERROR →
    本用例 FAIL（断言形态：正常构造 + 默认值）。GREEN：load_config_json 硬化
    isinstance(data, dict) 兜底（消费面已有同款风险顺带治愈）。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, [1, 2])

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_port == 8000
    assert settings.debug is False


# ── 【G】优先级序守护（现即 PASS，GREEN 后必须仍绿——防源插错序）──
def test_instance_env_beats_config_json(monkeypatch, tmp_path) -> None:
    """#987-B1【G】同键并存 instance.env 胜 config.json（方案 A 拍板：instance.env 高位）。

    现实现 instance.env 全键源（#977）生效、config.json 不读 → 值即 A（PASS）；
    GREEN 后 config.json 源必须排在 instance.env 源之后，仍取 A。
    """
    anchor = _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"llm_default_model": "json-side/value"})
    anchor.write_text("INKFLOW_LLM_DEFAULT_MODEL=instance-side/value\n", encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.llm_default_model == "instance-side/value"


def test_process_env_beats_config_json(monkeypatch, tmp_path) -> None:
    """#987-B2【G】进程 env 胜 config.json（D1 链：env 显式值高于一切文件源）。

    现实现 env 源消费 A、config.json 不读 → A（PASS）；GREEN 后仍须 A。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.setenv("INKFLOW_SERVER_PORT", "9000")
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"server_port": 8080})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_port == 9000


def test_dotenv_beats_config_json(monkeypatch, tmp_path) -> None:
    """#987-B3【G】.env 文件源胜 config.json（拍板序：.env > config.json——
    config.json 为最低文件源，应用内 GUI 面让位于显式 dotfile）。

    现实现 dotenv 消费 dotenv-host、config.json 不读 → dotenv-host（PASS）；
    GREEN 后 config.json 源必须排在 dotenv_settings 之后，仍 dotenv-host。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_SERVER_HOST", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("INKFLOW_SERVER_HOST=dotenv-host\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"server_host": "json-host"})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_host == "dotenv-host"


def test_debug_instance_env_true_beats_config_json_false(monkeypatch, tmp_path) -> None:
    """#987-D【G】debug 链零翻转补全组合：instance.env INKFLOW_DEBUG=1 +
    config.json debug=false → True（instance.env 命中即终止，不进 config.json）。

    现实现 _derive_paths 特判已满足（S3f 组镜像 test_config_instance_env.py:303
    反向组合）；GREEN 后 config.json debug 由源接管，本序仍须成立（F51 D1）。
    """
    anchor = _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    anchor.write_text("INKFLOW_DEBUG=1\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"debug": False})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.debug is True


# ── 【G】键过滤与值归一守护 ──
def test_config_json_unknown_keys_ignored(monkeypatch, tmp_path) -> None:
    """#987-E1【G】未知键（含 CLI 点号风格 "default.model"）不在 model_fields → 忽略，
    构造不抛、已知字段走默认。

    GREEN 义务第 3 条键过滤；payload 不含任何已知字段键 → RED/GREEN 两态断言同形
    （默认值 + 不抛异常），守护「无过滤直灌 pydantic 触发 extra/校验异常」永不发生。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_SERVER_PORT", raising=False)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"default.model": "a/b", "totally_unknown_key": "x"})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_port == 8000
    assert settings.llm_default_model == ""


def test_config_json_empty_string_value_skipped(monkeypatch, tmp_path) -> None:
    """#987-E2【G】值为空串的键跳过（镜像 load_instance_env 空值语义，不遮挡默认值）。

    GREEN 义务第 4 条；若 GREEN 误灌空串，float 字段 "" 会抛 ValidationError →
    本用例转为 ERROR，即该守护锁定此规则。现实现不读 → PASS。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    _write_config_json(data_dir, {"llm_temperature": "", "llm_default_model": ""})

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.llm_temperature == 0.7
    assert settings.llm_default_model == ""


def test_config_json_data_dir_key_never_startup_field(monkeypatch, tmp_path) -> None:
    """#987-H【G】config.json 手写 data_dir 键不作为启动字段（data-dir 唯一通道 =
    instance.env，#266/#977 语义；防定位环 + 越权改路径）。

    场景锁定「源接管后仍不可观察翻转」的形态：无构造参数/进程 env/instance.env 锚，
    dev 默认 data_dir = cwd/./data（chdir 隔离），其中 config.json 手写 data_dir=evil。
    RED（不读）→ data_dir 默认；GREEN 后源必须剔除 data_dir 键，否则 evil 覆盖默认
    路径并 mkdir → 断言 FAIL。GREEN 义务第 2 条剔除规则。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    cwd = tmp_path / "cwd"
    (cwd / "data").mkdir(parents=True)
    evil = tmp_path / "evil"
    (cwd / "data" / "config.json").write_text(
        json.dumps({"data_dir": str(evil)}), encoding="utf-8"
    )
    monkeypatch.chdir(cwd)

    settings = InkFlowConfig()

    assert settings.data_dir == Path("data") or settings.data_dir == cwd / "data"
    assert not evil.exists()


def test_construction_survives_broken_config_json(monkeypatch, tmp_path) -> None:
    """#987-F【G】config.json 语法损坏（JSONDecodeError）→ 构造不抛，全字段默认
    （load_config_json 既有 warning 兜底语义延伸到启动源消费面）。

    现实现 validator debug 分支已兜住（构造 PASS + 默认值）→ 现即 PASS；
    GREEN 后启动源同样不得因损坏文件炸掉内核启动。
    """
    _empty_anchor(monkeypatch, tmp_path)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "config.json").write_text("{broken json", encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.server_port == 8000
    assert settings.llm_default_model == ""
