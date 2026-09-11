"""密钥自举契约 RED（#1096）— ``core.config.load_or_create_secret_key``。

规则 1p（既有 config 模块追加函数整组 RED）：模块已存在、新函数缺失
→ 顶部 import 收集期 ``ImportError: cannot import name``（exit 2）。

契约来源：specs/f61-secret-bootstrap/spec.md §3.2 / §3.4 / §4.1。

设计假设（父侧定稿，GREEN 逐条遵守）：
  1. ``load_or_create_secret_key(data_dir: Path) -> str`` —— 读取
     ``<data_dir>/keys/.secret_key``；缺失则生成 —— **64 hex chars**
     （= 32 bytes，与 ``APIKeyManager._get_or_derive_key`` 的
     ``bytes.fromhex`` 期望一致）。
  2. **幂等（D2，最高危）**：文件已存在 → 读回原值，**绝不重新生成**
     —— 重新生成会让已加密的 ``keys/*.json`` 全部解不开（不可逆）。
  3. 空内容文件（D3/边界 3）→ 返回 "" 且 **不覆盖**（保守：宁可明文降级，
     不覆盖可能有效的密钥文件）。
  4. IO 失败（边界 5）→ 返回 ""，**不抛异常**（不阻断启动）。
  5. POSIX 权限 0600（D4）；Windows 跳过（NTFS 无 POSIX 权限位语义）。
  6. 装配（§3.3）：``InkFlowConfig`` 在 ``secret_key`` 未显式设置时调用本函数
     回写字段；显式 ``INKFLOW_SECRET_KEY`` 时**零文件系统访问**（D6/E10）。

RED 预期形态（两阶段）：
  - 纯 RED：收集期 ``ImportError: cannot import name 'load_or_create_secret_key'``
    （exit 2，本文件 11 用例全部不执行）。
  - 函数补齐后：E1-E5/E9-E11 按契约断言；其中 **E10/E11 为守护用例**，
    RED 阶段即 PASS 属刻意为之（详见各用例 docstring）。

父侧裁定（2026-09-11）：
  - 导入形态：**必须用 ``importlib.import_module("inkflow.core.config")``**，禁用
    ``from inkflow.core import config as config_mod``——后者绑定的是**模块级单例
    实例**（`inkflow.core` 包的 `config` 属性被 L379 的 `config = InkFlowConfig()`
    遮蔽），属性访问会落到 Pydantic `__getattr__`，报
    `'InkFlowConfig' object has no attribute ...`（实测踩中）。
  - 因此本文件经模块对象属性访问 `config_mod.load_or_create_secret_key` —— 让
    RED 期失败落在**用例体 AttributeError**（逐用例干净 FAILED），而非顶部
    import 的收集期错误连坐既有模块用例。config 模块本身**已存在**。
  - 该形态同时使 patch/注入无需改动 import 块（GREEN 后零 churn）。
"""

from __future__ import annotations

import importlib
import re
import sys

import pytest

config_mod = importlib.import_module("inkflow.core.config")

# 64 hex chars = 32 bytes 的形态判据
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture
def fresh_data_dir(tmp_path):
    """全新数据目录（无 keys/、无密钥文件）。"""
    return tmp_path / "fresh-data"


class TestLoadOrCreateSecretKey:
    """``load_or_create_secret_key`` 契约套件（E1-E5）。"""

    # ── E1 全新目录生成 ──

    def test_generates_key_on_fresh_dir(self, fresh_data_dir):
        """E1：全新目录 → 返回 64 hex；``keys/.secret_key`` 落盘且内容一致。"""
        key = config_mod.load_or_create_secret_key(fresh_data_dir)

        assert HEX64.match(key), f"密钥形态应为 64 hex chars，实际: {key!r}"
        key_file = fresh_data_dir / "keys" / ".secret_key"
        assert key_file.exists(), "密钥文件未落盘"
        assert key_file.read_text(encoding="utf-8").strip() == key

    # ── E2 幂等（不可逆风险守护，D2）──

    def test_existing_key_is_reused_not_regenerated(self, fresh_data_dir):
        """E2【最高危守护】：二次调用返回**相同**密钥，文件内容不变。

        若 GREEN 每次生成新密钥 → 已加密的 keys/*.json 全部解不开
        （不可逆数据丢失）——本用例是 A 方案的唯一防线。
        """
        first = config_mod.load_or_create_secret_key(fresh_data_dir)
        key_file = fresh_data_dir / "keys" / ".secret_key"
        mtime_before = key_file.stat().st_mtime_ns

        second = config_mod.load_or_create_secret_key(fresh_data_dir)

        assert second == first, "二次调用重新生成了密钥 —— 存量密文将不可解（不可逆）"
        assert key_file.read_text(encoding="utf-8").strip() == first
        assert key_file.stat().st_mtime_ns == mtime_before, "已存在的密钥文件被重写"

    # ── E3 权限 0600（D4）──

    @pytest.mark.skipif(sys.platform == "win32", reason="NTFS 无 POSIX 权限位语义")
    def test_posix_file_mode_is_0600(self, fresh_data_dir):
        """E3：POSIX 下密钥文件权限必须是 0600（仅属主可读写）。"""
        config_mod.load_or_create_secret_key(fresh_data_dir)
        key_file = fresh_data_dir / "keys" / ".secret_key"

        assert (key_file.stat().st_mode & 0o777) == 0o600

    # ── E4 空内容文件不覆盖（边界 3）──

    def test_empty_existing_file_returns_empty_and_is_not_overwritten(self, fresh_data_dir):
        """E4：已存在但内容为空 → 返回 ""，且**不覆盖**该文件。"""
        keys_dir = fresh_data_dir / "keys"
        keys_dir.mkdir(parents=True)
        key_file = keys_dir / ".secret_key"
        key_file.write_text("", encoding="utf-8")

        result = config_mod.load_or_create_secret_key(fresh_data_dir)

        assert result == "", "空内容文件应退化为空串（保守降级）"
        assert key_file.read_text(encoding="utf-8") == "", "空内容文件被覆盖"

    # ── E5 IO 失败降级（边界 5）──

    def test_io_failure_returns_empty_without_raising(self, fresh_data_dir):
        """E5：``keys/`` 路径被同名**文件**占位 → 返回 ""，不抛异常。"""
        fresh_data_dir.mkdir(parents=True)
        (fresh_data_dir / "keys").write_text("not a directory", encoding="utf-8")

        result = config_mod.load_or_create_secret_key(fresh_data_dir)

        assert result == "", "IO 失败应降级为空串，不阻断启动"


class TestConfigWiring:
    """装配契约（E9-E11，§3.3）。"""

    def test_config_bootstraps_secret_key_when_absent(self, fresh_data_dir, monkeypatch):
        """E9：``secret_key`` 未显式设置 → InkFlowConfig 实例化后字段非空且等于文件值。"""
        monkeypatch.delenv("INKFLOW_SECRET_KEY", raising=False)
        # setup 阶段让 module 属性可解析（RED 期函数不存在时静默创建无害属性，
        # 不污染失败形态）；GREEN 期该函数真实存在，setattr 覆盖为同一实现。
        real = getattr(config_mod, "load_or_create_secret_key", None)
        if real is not None:
            monkeypatch.setattr(config_mod, "load_or_create_secret_key", real, raising=False)

        cfg = config_mod.InkFlowConfig(data_dir=fresh_data_dir)

        assert cfg.secret_key, "配置装配未自举密钥（secret_key 仍为空）"
        assert HEX64.match(cfg.secret_key), f"自举密钥形态不符: {cfg.secret_key!r}"
        key_file = fresh_data_dir / "keys" / ".secret_key"
        assert key_file.read_text(encoding="utf-8").strip() == cfg.secret_key

    # ── E10/E11 守护用例（RED 期即 PASS 刻意，docstring 注明）──

    def test_explicit_env_secret_key_wins_and_no_file_created(self, fresh_data_dir, monkeypatch):
        """E10【守护，RED 期 PASS 刻意】：显式 env → 字段取 env 值，且不落盘。

        守护语义：锁「自举只在 secret_key 未显式设置时触发」——若 GREEN 无条件
        自举，本用例失败点 = 文件被创建（或字段被覆盖）。
        """
        explicit = "f" * 64
        monkeypatch.setenv("INKFLOW_SECRET_KEY", explicit)

        cfg = config_mod.InkFlowConfig(data_dir=fresh_data_dir)

        assert cfg.secret_key == explicit
        assert not (
            fresh_data_dir / "keys" / ".secret_key"
        ).exists(), "显式 INKFLOW_SECRET_KEY 时不应触碰文件系统（D6）"

    def test_explicit_env_does_not_call_bootstrap(self, fresh_data_dir, monkeypatch):
        """E11【守护，RED 期 PASS 刻意】：显式 env → 自举函数零调用。

        用调用计数器（而非文件不存在）锁「零文件系统访问」——
        比 E10 的文件断言更强：覆盖 GREEN 先调后回滚的实现。
        """
        explicit = "a" * 64
        monkeypatch.setenv("INKFLOW_SECRET_KEY", explicit)
        calls: list[object] = []

        def _spy(data_dir):
            calls.append(data_dir)
            return "b" * 64

        monkeypatch.setattr(config_mod, "load_or_create_secret_key", _spy, raising=False)

        cfg = config_mod.InkFlowConfig(data_dir=fresh_data_dir)

        assert cfg.secret_key == explicit
        assert calls == [], f"显式 env 下自举被调用 {len(calls)} 次，应为 0"
