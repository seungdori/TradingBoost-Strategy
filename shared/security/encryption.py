"""
API Key Encryption Module for TradingBoost-Strategy

Provides Fernet-based symmetric encryption for sensitive data like API keys.

Security Features:
- AES-128 encryption in CBC mode
- HMAC for authentication
- Random IV for each encryption
- Base64 encoding for storage compatibility

Usage:
    from shared.security import encrypt_api_key, decrypt_api_key

    # Encrypt
    encrypted = encrypt_api_key("my_secret_key")

    # Decrypt
    original = decrypt_api_key(encrypted)

Environment Variables:
    ENCRYPTION_KEY: Base64-encoded Fernet key (required)

Generate key:
    python scripts/generate_encryption_key.py
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)


class EncryptionError(Exception):
    """Custom exception for encryption/decryption errors"""
    pass


# Encryption prefix to identify encrypted values
ENCRYPTION_PREFIX = "enc_v1:"


def _get_cipher() -> Fernet:
    """
    Get Fernet cipher instance from environment variable.

    Returns:
        Fernet: Initialized cipher

    Raises:
        EncryptionError: If ENCRYPTION_KEY is not set or invalid
    """
    encryption_key = os.environ.get("ENCRYPTION_KEY") or settings.ENCRYPTION_KEY

    if not encryption_key:
        raise EncryptionError(
            "ENCRYPTION_KEY environment variable not set. "
            "Generate a key with: python scripts/generate_encryption_key.py"
        )

    try:
        # Ensure the key is properly formatted
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()

        return Fernet(encryption_key)
    except Exception as e:
        raise EncryptionError(f"Invalid ENCRYPTION_KEY format: {e}")


def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt an API key using Fernet symmetric encryption.

    Args:
        api_key: Plaintext API key to encrypt

    Returns:
        str: Encrypted API key with version prefix (e.g., "enc_v1:...")

    Raises:
        EncryptionError: If encryption fails

    Example:
        >>> encrypted = encrypt_api_key("my_secret_api_key")
        >>> print(encrypted)
        enc_v1:gAAAAABh...
    """
    if not api_key:
        raise EncryptionError("Cannot encrypt empty API key")

    try:
        cipher = _get_cipher()

        # Encrypt the API key
        encrypted_bytes = cipher.encrypt(api_key.encode())

        # Convert to string and add version prefix
        encrypted_str = encrypted_bytes.decode()
        return f"{ENCRYPTION_PREFIX}{encrypted_str}"

    except EncryptionError:
        raise
    except Exception as e:
        logger.error(f"API key encryption failed: {e}", exc_info=True)
        raise EncryptionError(f"Encryption failed: {e}")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key encrypted with encrypt_api_key().

    Supports backward compatibility:
    - If key starts with ENCRYPTION_PREFIX, decrypt it
    - Otherwise, assume it's plaintext (for migration)

    Args:
        encrypted_key: Encrypted API key (with or without prefix)

    Returns:
        str: Decrypted plaintext API key

    Raises:
        EncryptionError: If decryption fails

    Example:
        >>> encrypted = "enc_v1:gAAAAABh..."
        >>> decrypted = decrypt_api_key(encrypted)
        >>> print(decrypted)
        my_secret_api_key
    """
    if not encrypted_key:
        raise EncryptionError("Cannot decrypt empty value")

    # Backward compatibility: If not encrypted, return as-is
    if not encrypted_key.startswith(ENCRYPTION_PREFIX):
        logger.warning(
            "Detected unencrypted API key - consider re-saving with encryption",
            extra={"key_preview": encrypted_key[:10] + "..."}
        )
        return encrypted_key

    try:
        cipher = _get_cipher()

        # Remove version prefix
        encrypted_str = encrypted_key[len(ENCRYPTION_PREFIX):]

        # Decrypt
        encrypted_bytes = encrypted_str.encode()
        decrypted_bytes = cipher.decrypt(encrypted_bytes)

        return decrypted_bytes.decode()

    except InvalidToken:
        raise EncryptionError(
            "Decryption failed - invalid key or corrupted data"
        )
    except EncryptionError:
        raise
    except Exception as e:
        logger.error(f"API key decryption failed: {e}", exc_info=True)
        raise EncryptionError(f"Decryption failed: {e}")


def is_encrypted(value: str) -> bool:
    """
    Check if a value is encrypted.

    Args:
        value: String to check

    Returns:
        bool: True if encrypted, False otherwise

    Example:
        >>> is_encrypted("enc_v1:gAAAAABh...")
        True
        >>> is_encrypted("plaintext_value")
        False
    """
    return value.startswith(ENCRYPTION_PREFIX) if value else False


def migrate_plaintext_key(
    old_key: str,
    key_name: str = "api_key"
) -> tuple[str, bool]:
    """
    Helper function to migrate plaintext keys to encrypted format.

    Args:
        old_key: Existing key (plaintext or encrypted)
        key_name: Name of the key (for logging)

    Returns:
        tuple: (processed_key, was_migrated)
            - processed_key: Encrypted key (newly encrypted if was plaintext)
            - was_migrated: True if encryption was applied, False if already encrypted

    Example:
        >>> key, migrated = migrate_plaintext_key("old_plaintext_key")
        >>> if migrated:
        ...     print("Key was encrypted and should be saved")
    """
    if is_encrypted(old_key):
        # Already encrypted, no migration needed
        return old_key, False

    try:
        # Encrypt the plaintext key
        encrypted = encrypt_api_key(old_key)
        logger.info(
            f"Migrated {key_name} from plaintext to encrypted format",
            extra={"key_name": key_name}
        )
        return encrypted, True

    except EncryptionError as e:
        logger.error(
            f"Failed to migrate {key_name}: {e}",
            extra={"key_name": key_name}
        )
        # Return original key if migration fails
        return old_key, False


# =============================================================================
# Additional Security Utilities
# =============================================================================

def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        str: Base64-encoded encryption key

    Example:
        >>> key = generate_encryption_key()
        >>> print(f"ENCRYPTION_KEY={key}")
        ENCRYPTION_KEY=abc123...
    """
    return Fernet.generate_key().decode()


def rotate_key(
    old_encrypted: str,
    new_encryption_key: Optional[str] = None
) -> str:
    """
    Rotate encryption key for an encrypted value.

    Decrypts with current key and re-encrypts with new key.

    Args:
        old_encrypted: Value encrypted with old key
        new_encryption_key: New Fernet key (if None, uses current ENCRYPTION_KEY)

    Returns:
        str: Value re-encrypted with new key

    Raises:
        EncryptionError: If rotation fails
    """
    # Decrypt with current key
    plaintext = decrypt_api_key(old_encrypted)

    # Re-encrypt with new key
    if new_encryption_key:
        # Temporarily override ENCRYPTION_KEY
        old_key = os.environ.get("ENCRYPTION_KEY")
        try:
            os.environ["ENCRYPTION_KEY"] = new_encryption_key
            return encrypt_api_key(plaintext)
        finally:
            if old_key:
                os.environ["ENCRYPTION_KEY"] = old_key
            else:
                os.environ.pop("ENCRYPTION_KEY", None)
    else:
        return encrypt_api_key(plaintext)
