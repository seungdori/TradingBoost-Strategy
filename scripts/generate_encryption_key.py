#!/usr/bin/env python3
"""
Generate Encryption Key for API Key Security

Generates a Fernet encryption key for use with the API key encryption system.

Usage:
    # Generate and print to stdout
    python scripts/generate_encryption_key.py

    # Append to .env file
    python scripts/generate_encryption_key.py >> .env

    # Save to specific file
    python scripts/generate_encryption_key.py > encryption.key

Security Notes:
    - Store the key securely (environment variable or secret manager)
    - Never commit the key to version control
    - Rotate keys periodically for enhanced security
    - Backup the key before rotation (needed to decrypt old data)
"""

import sys
from cryptography.fernet import Fernet


def generate_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        str: Base64-encoded encryption key
    """
    return Fernet.generate_key().decode()


def main():
    """Main entry point"""
    # Generate key
    key = generate_key()

    # Print in .env format
    print(f"# Fernet encryption key for API key security")
    print(f"# Generated: {__file__}")
    print(f"# WARNING: Keep this key secret and secure!")
    print(f"ENCRYPTION_KEY={key}")

    # Print instructions to stderr (won't interfere with >> redirection)
    print("\n" + "=" * 70, file=sys.stderr)
    print("✅ Encryption key generated successfully!", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("\nNext steps:", file=sys.stderr)
    print("1. Add the key to your .env file", file=sys.stderr)
    print("2. Restart your application to apply the changes", file=sys.stderr)
    print("3. Existing plaintext API keys will be migrated automatically", file=sys.stderr)
    print("\n⚠️  SECURITY WARNING:", file=sys.stderr)
    print("   - Never commit this key to version control", file=sys.stderr)
    print("   - Store securely (environment variable or secret manager)", file=sys.stderr)
    print("   - Backup before key rotation", file=sys.stderr)
    print("=" * 70, file=sys.stderr)


if __name__ == "__main__":
    main()
