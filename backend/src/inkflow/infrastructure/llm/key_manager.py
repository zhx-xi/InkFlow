"""API Key 本地加密存储 — AES-256-GCM 加密。

开发模式（secret_key=""）：明文存储 + WARNING 日志。
生产模式：GCM 认证加密，nonce 随机生成。
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger


class APIKeyManager:
    """管理 API Key 的本地加密存储与读取。

    Args:
        secret_key: 32 字节 hex 密钥（通过环境变量注入）。为空时使用明文模式。
        storage_dir: 密文存储目录。
    """

    def __init__(self, secret_key: str, storage_dir: Path) -> None:
        self._secret_key = secret_key
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        if not secret_key:
            logger.warning(
                "INKFLOW_SECRET_KEY is empty — API keys will be stored in plaintext (dev mode)"
            )

    # ── Public API ──

    def encrypt(self, provider: str, api_key: str) -> dict:
        """加密 API Key。

        Returns:
            dict with keys: provider, ciphertext_b64, nonce_b64
        """
        key_bytes = self._get_or_derive_key()
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key_bytes)
        ciphertext = aesgcm.encrypt(nonce, api_key.encode("utf-8"), None)
        return {
            "provider": provider,
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        }

    def decrypt(self, provider: str, encrypted_data: dict | None = None) -> str:
        """解密 API Key。

        Args:
            provider: Provider 名称。
            encrypted_data: 加密数据字典。None 时从文件加载。

        Returns:
            明文 API Key。
        """
        if encrypted_data is None:
            encrypted_data = self._read_json(provider)

        key_bytes = self._get_or_derive_key()
        nonce = base64.b64decode(encrypted_data["nonce_b64"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext_b64"])
        aesgcm = AESGCM(key_bytes)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

    def store(self, provider: str, api_key: str) -> None:
        """加密并存储 API Key 到本地文件。"""
        if not self._secret_key:
            self._write_plaintext(provider, api_key)
        else:
            data = self.encrypt(provider, api_key)
            self._write_json(provider, data)

    def load(self, provider: str) -> str:
        """从本地文件加载并解密 API Key。"""
        if not self._secret_key:
            return self._read_plaintext(provider)
        data = self._read_json(provider)
        return self.decrypt(provider, encrypted_data=data)

    def delete(self, provider: str) -> None:
        """删除指定 Provider 的 Key 文件。"""
        for ext in (".key", ".json", ".enc"):
            path = self._key_path(provider, ext)
            if path.exists():
                path.unlink()
                return
        raise FileNotFoundError(f"No key file found for provider: {provider}")

    def list_providers(self) -> list[str]:
        """列出已存储的 Provider 名称。"""
        providers: list[str] = []
        for path in self._storage_dir.iterdir():
            if path.suffix in (".key", ".json", ".enc"):
                providers.append(path.stem)
        return sorted(providers)

    # ── Private helpers ──

    def _get_or_derive_key(self) -> bytes:
        if not self._secret_key:
            return b"\x00" * 32  # Placeholder, plaintext mode won't use
        return bytes.fromhex(self._secret_key)

    def _key_path(self, provider: str, ext: str = ".key") -> Path:
        return self._storage_dir / f"{provider}{ext}"

    def _write_json(self, provider: str, data: dict) -> None:
        path = self._key_path(provider, ".json")
        path.write_text(json.dumps(data), encoding="utf-8")

    def _read_json(self, provider: str) -> dict:
        path = self._key_path(provider, ".json")
        if not path.exists():
            raise FileNotFoundError(f"No key file for provider: {provider}")
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def _write_plaintext(self, provider: str, api_key: str) -> None:
        path = self._key_path(provider, ".key")
        path.write_text(api_key, encoding="utf-8")

    def _read_plaintext(self, provider: str) -> str:
        path = self._key_path(provider, ".key")
        if not path.exists():
            raise FileNotFoundError(f"No key file for provider: {provider}")
        return path.read_text(encoding="utf-8").strip()
