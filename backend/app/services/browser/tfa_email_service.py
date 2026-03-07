"""
2FA Email Service — extract verification codes from email.

Checks the user's inbox for 2FA codes sent during login flows.

TODO: Implement email integration (Gmail API or IMAP).
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def extract_2fa_code_from_email(
    user_id: str,
    site_domain: str,
) -> Optional[str]:
    """Extract a 2FA verification code from the user's email inbox.

    Args:
        user_id:     The user's ID.
        site_domain: Domain that sent the 2FA code (for filtering emails).

    Returns:
        The extracted code string, or None if not found.
    """
    # TODO: Implement email-based 2FA code extraction
    logger.warning(
        "[TFAEmailService] Email 2FA extraction not yet implemented "
        "(user=%s, domain=%s)",
        user_id,
        site_domain,
    )
    return None
