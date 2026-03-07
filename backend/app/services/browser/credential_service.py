"""
Browser Credential Service — secure credential retrieval for browser login.

Retrieves stored credentials with domain validation to prevent credential
injection into unrelated sites.

TODO: Wire to Supabase credential storage. Currently a stub.
"""

import logging
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BrowserCredentialService:
    """Service for securely retrieving stored browser credentials."""

    async def get_credential(
        self,
        user_id: str,
        site_domain: str,
        current_page_url: str,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a stored credential for the given site domain.

        Validates that the current page URL matches the credential's domain
        to prevent credential injection attacks.

        Args:
            user_id:          The user's ID.
            site_domain:      Domain of the stored credential (e.g. 'facebook.com').
            current_page_url: The browser's current URL (for domain validation).

        Returns:
            Dict with 'username', 'password', and optionally 'totp_secret',
            or None if not found / domain mismatch.
        """
        # Validate that current page matches the credential domain
        try:
            parsed = urlparse(current_page_url)
            page_host = parsed.hostname or ""
            if not page_host.endswith(site_domain) and site_domain not in page_host:
                logger.warning(
                    "[CredentialService] Domain mismatch: credential=%s page=%s",
                    site_domain,
                    page_host,
                )
                return None
        except Exception:
            return None

        # TODO: Retrieve from Supabase encrypted credential store
        logger.warning(
            "[CredentialService] Credential retrieval not yet implemented "
            "(user=%s, domain=%s)",
            user_id,
            site_domain,
        )
        return None

    def generate_totp_code(self, totp_secret: str) -> str:
        """Generate a TOTP code from a stored secret.

        TODO: Implement with pyotp.
        """
        raise NotImplementedError("TOTP code generation not yet implemented")


_service_instance: Optional[BrowserCredentialService] = None


def get_browser_credential_service() -> BrowserCredentialService:
    """Get or create the singleton credential service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = BrowserCredentialService()
    return _service_instance
