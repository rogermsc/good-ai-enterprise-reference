"""
Encryption utilities for sensitive data at rest.

Provides encryption for:
- Token maps containing PII mappings
- Any sensitive data stored in the database

Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
"""

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""

    pass


class TokenMapEncryption:
    """
    Encryption service for token maps.

    Token maps contain the mapping from PII tokens to original values.
    This data must be encrypted at rest for compliance.

    Example:
        encryption = TokenMapEncryption()

        # Encrypt before storing
        encrypted = encryption.encrypt({"[PII_EMAIL_1]": "user@example.com"})

        # Decrypt when retrieving
        token_map = encryption.decrypt(encrypted)
    """

    def __init__(self, encryption_key: str | None = None):
        """
        Initialize encryption with key.

        Args:
            encryption_key: Base64-encoded 32-byte key.
                           If not provided, reads from ENCRYPTION_KEY env var.
                           If env var not set, generates a key (development only).
        """
        self._fernet = self._create_fernet(encryption_key)

    def _create_fernet(self, encryption_key: str | None) -> Fernet:
        """Create Fernet instance from key."""
        if encryption_key:
            key = encryption_key.encode()
        else:
            key_from_env = os.environ.get("ENCRYPTION_KEY")
            if key_from_env:
                key = key_from_env.encode()
            else:
                # Development fallback - derive key from a known passphrase
                # WARNING: In production, always set ENCRYPTION_KEY
                key = self._derive_key_from_passphrase("development-only-key")

        # Validate key format
        try:
            return Fernet(key)
        except Exception as e:
            raise EncryptionError(
                f"Invalid encryption key format. Expected base64-encoded 32-byte key: {e}"
            ) from e

    def _derive_key_from_passphrase(self, passphrase: str) -> bytes:
        """Derive a Fernet-compatible key from a passphrase."""
        # Use a fixed salt for development (in production, use env var key)
        salt = b"goodai-dev-salt-"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        return key

    def encrypt(self, token_map: dict[str, str]) -> str:
        """
        Encrypt a token map.

        Args:
            token_map: Dictionary mapping tokens to original PII values

        Returns:
            Base64-encoded encrypted string

        Raises:
            EncryptionError: If encryption fails
        """
        try:
            json_data = json.dumps(token_map)
            encrypted = self._fernet.encrypt(json_data.encode())
            return encrypted.decode()
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt token map: {e}") from e

    def decrypt(self, encrypted_data: str) -> dict[str, str]:
        """
        Decrypt a token map.

        Args:
            encrypted_data: Base64-encoded encrypted string

        Returns:
            Decrypted token map dictionary

        Raises:
            EncryptionError: If decryption fails
        """
        try:
            decrypted = self._fernet.decrypt(encrypted_data.encode())
            result: dict[str, str] = json.loads(decrypted.decode())
            return result
        except InvalidToken as e:
            raise EncryptionError(
                "Failed to decrypt token map: invalid key or corrupted data"
            ) from e
        except json.JSONDecodeError as e:
            raise EncryptionError(
                f"Failed to parse decrypted token map as JSON: {e}"
            ) from e
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt token map: {e}") from e

    def encrypt_value(self, value: str) -> str:
        """Encrypt a single string value."""
        try:
            encrypted = self._fernet.encrypt(value.encode())
            return encrypted.decode()
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt value: {e}") from e

    def decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a single string value."""
        try:
            decrypted = self._fernet.decrypt(encrypted_value.encode())
            return decrypted.decode()
        except InvalidToken as e:
            raise EncryptionError(
                "Failed to decrypt value: invalid key or corrupted data"
            ) from e
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt value: {e}") from e


# Module-level instance for convenience
_default_encryption: TokenMapEncryption | None = None


def get_encryption() -> TokenMapEncryption:
    """Get default encryption instance."""
    global _default_encryption
    if _default_encryption is None:
        _default_encryption = TokenMapEncryption()
    return _default_encryption


def encrypt_token_map(token_map: dict[str, str]) -> str:
    """Convenience function to encrypt a token map."""
    return get_encryption().encrypt(token_map)


def decrypt_token_map(encrypted_data: str) -> dict[str, str]:
    """Convenience function to decrypt a token map."""
    return get_encryption().decrypt(encrypted_data)


def generate_key() -> str:
    """
    Generate a new encryption key.

    Returns:
        Base64-encoded 32-byte key suitable for ENCRYPTION_KEY env var
    """
    return Fernet.generate_key().decode()
