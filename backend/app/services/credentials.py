"""
Credential Service — Encrypted storage and retrieval of platform credentials.

Stores Facebook (and other platform) credentials encrypted with Fernet symmetric
encryption. The encryption key is derived from the Supabase service role key,
so credentials are only decryptable by the backend.
"""

import base64
import hashlib
import logging
from typing import Optional

import httpx
from cryptography.fernet import Fernet

from app.config import get_settings

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret string."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


class CredentialService:
    """Encrypts, stores, and retrieves platform credentials via Supabase."""

    def __init__(self):
        settings = get_settings()
        self._fernet = Fernet(_derive_fernet_key(settings.SUPABASE_SERVICE_ROLE_KEY))
        self._rest_url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1"
        self._headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(15.0),
        )

    def _encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    async def store_credentials(
        self,
        user_id: str,
        platform: str,
        email: str,
        password: str,
    ) -> dict:
        """Encrypt and store platform credentials.

        Args:
            user_id:  The user's UUID.
            platform: Platform name ('facebook', 'craigslist', etc.).
            email:    Platform login email.
            password: Platform login password.

        Returns:
            The stored credential record (without decrypted values).
        """
        payload = {
            "user_id": user_id,
            "platform": platform,
            "encrypted_email": self._encrypt(email),
            "encrypted_password": self._encrypt(password),
            "is_active": True,
            "login_status": "pending",
        }

        # Upsert on (user_id, platform) unique constraint
        resp = await self._client.post(
            f"{self._rest_url}/platform_credentials",
            json=payload,
            headers={
                **self._headers,
                "Prefer": "return=representation,resolution=merge-duplicates",
            },
        )
        resp.raise_for_status()
        result = resp.json()
        record = result[0] if isinstance(result, list) else result
        logger.info("Stored %s credentials for user=%s", platform, user_id)
        return {
            "id": record.get("id"),
            "platform": platform,
            "login_status": record.get("login_status"),
            "is_active": True,
        }

    async def get_credentials(
        self,
        user_id: str,
        platform: str,
    ) -> Optional[dict]:
        """Retrieve and decrypt platform credentials.

        Returns:
            Dict with email, password, login_status, or None if not found.
        """
        resp = await self._client.get(
            f"{self._rest_url}/platform_credentials",
            params={
                "user_id": f"eq.{user_id}",
                "platform": f"eq.{platform}",
                "is_active": "eq.true",
                "select": "id,encrypted_email,encrypted_password,login_status,last_login_at",
                "limit": "1",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None

        row = rows[0]
        return {
            "id": row["id"],
            "email": self._decrypt(row["encrypted_email"]),
            "password": self._decrypt(row["encrypted_password"]),
            "login_status": row["login_status"],
            "last_login_at": row.get("last_login_at"),
        }

    async def update_login_status(
        self,
        user_id: str,
        platform: str,
        status: str,
    ) -> None:
        """Update the login status after an attempt."""
        resp = await self._client.patch(
            f"{self._rest_url}/platform_credentials",
            params={
                "user_id": f"eq.{user_id}",
                "platform": f"eq.{platform}",
            },
            json={
                "login_status": status,
                "last_login_at": "now()",
                "updated_at": "now()",
            },
        )
        resp.raise_for_status()

    async def delete_credentials(
        self,
        user_id: str,
        platform: str,
    ) -> None:
        """Delete stored credentials for a platform."""
        resp = await self._client.delete(
            f"{self._rest_url}/platform_credentials",
            params={
                "user_id": f"eq.{user_id}",
                "platform": f"eq.{platform}",
            },
        )
        resp.raise_for_status()
        logger.info("Deleted %s credentials for user=%s", platform, user_id)

    async def close(self):
        await self._client.aclose()
