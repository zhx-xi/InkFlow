"""APIKeyManager 单元测试 — AES-256-GCM 加解密。"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from inkflow.infrastructure.llm.key_manager import APIKeyManager


class TestAPIKeyManager:
    """APIKeyManager 加解密测试套件。"""

    @pytest.fixture
    def secret_key(self) -> str:
        """64 hex chars = 32 bytes = AES-256 密钥。"""
        return "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0a1b2"

    @pytest.fixture
    def key_manager(self, secret_key, temp_keys_dir):
        return APIKeyManager(secret_key=secret_key, storage_dir=temp_keys_dir)

    # ── 加解密往返 ──

    def test_encrypt_decrypt_roundtrip(self, key_manager):
        """加密后解密应得到原始明文。"""
        plaintext = "sk-test-api-key-12345"
        encrypted = key_manager.encrypt("openai", plaintext)
        decrypted = key_manager.decrypt("openai", encrypted_data=encrypted)
        assert decrypted == plaintext

    # ── 持久化往返 ──

    def test_store_and_load(self, key_manager):
        """存储到文件后再加载应得到原始明文。"""
        plaintext = "sk-persisted-key"
        key_manager.store("deepseek", plaintext)
        loaded = key_manager.load("deepseek")
        assert loaded == plaintext

    # ── 不同 Provider 独立 ──

    def test_different_providers_independent(self, key_manager):
        """不同 Provider 的 Key 互不影响。"""
        key_manager.store("openai", "key-openai")
        key_manager.store("deepseek", "key-deepseek")
        assert key_manager.load("openai") == "key-openai"
        assert key_manager.load("deepseek") == "key-deepseek"

    # ── 删除 ──

    def test_delete(self, key_manager):
        """删除后加载应失败。"""
        key_manager.store("openai", "temp-key")
        key_manager.delete("openai")
        with pytest.raises(FileNotFoundError):
            key_manager.load("openai")

    # ── 列出 Provider ──

    def test_list_providers(self, key_manager):
        """列出已存储 Provider 名称。"""
        key_manager.store("openai", "k1")
        key_manager.store("anthropic", "k2")
        providers = key_manager.list_providers()
        assert set(providers) == {"openai", "anthropic"}

    def test_list_providers_empty(self, key_manager):
        """无存储时应返回空列表。"""
        assert key_manager.list_providers() == []

    # ── 错误场景 ──

    def test_load_nonexistent(self, key_manager):
        """加载不存在的 Provider 应抛异常。"""
        with pytest.raises(FileNotFoundError):
            key_manager.load("nonexistent")

    def test_plaintext_mode(self, temp_keys_dir):
        """空 secret_key 时明文存储（开发模式）。"""
        mgr = APIKeyManager(secret_key="", storage_dir=temp_keys_dir)
        mgr.store("openai", "plain-key")
        loaded = mgr.load("openai")
        assert loaded == "plain-key"

    def test_encrypt_with_different_keys(self, secret_key, temp_keys_dir):
        """用不同密钥加密的数据无法解密。"""
        mgr1 = APIKeyManager(secret_key=secret_key, storage_dir=temp_keys_dir)
        encrypted = mgr1.encrypt("openai", "secret-data")

        other_key = "f" * 64
        mgr2 = APIKeyManager(secret_key=other_key, storage_dir=temp_keys_dir)
        with pytest.raises(InvalidTag):
            mgr2.decrypt("openai", encrypted_data=encrypted)

    # ── Phase 3 覆盖率补齐（#104）──────────────────────────────────

    def test_decrypt_without_data_loads_from_file(self, key_manager):
        """encrypted_data=None → 从本地文件读取密文后解密。"""
        key_manager.store("openai", "file-key")
        assert key_manager.decrypt("openai") == "file-key"

    def test_delete_nonexistent_raises(self, key_manager):
        """删除不存在的 Provider → FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            key_manager.delete("ghost")

    def test_list_providers_ignores_unrelated_files(self, key_manager, temp_keys_dir):
        """目录中的非密钥文件（.txt 等）不参与 Provider 列表。"""
        (Path(temp_keys_dir) / "notes.txt").write_text("not a key", encoding="utf-8")
        key_manager.store("openai", "k1")
        assert key_manager.list_providers() == ["openai"]

    def test_plaintext_encrypt_decrypt_roundtrip(self, temp_keys_dir):
        """空 secret_key 下 encrypt/decrypt 走占位零密钥（dev 模式防呆）。"""
        mgr = APIKeyManager(secret_key="", storage_dir=temp_keys_dir)
        encrypted = mgr.encrypt("openai", "dev-key")
        assert "ciphertext_b64" in encrypted
        assert "nonce_b64" in encrypted
        assert mgr.decrypt("openai", encrypted_data=encrypted) == "dev-key"

    def test_plaintext_load_strips_whitespace(self, temp_keys_dir):
        """明文模式读取时去除首尾空白（.strip）。"""
        mgr = APIKeyManager(secret_key="", storage_dir=temp_keys_dir)
        mgr.store("openai", "  spaced-key  ")
        assert mgr.load("openai") == "spaced-key"

    def test_plaintext_load_missing_raises(self, temp_keys_dir):
        """明文模式加载不存在的 Provider → FileNotFoundError。"""
        mgr = APIKeyManager(secret_key="", storage_dir=temp_keys_dir)
        with pytest.raises(FileNotFoundError):
            mgr.load("ghost")
