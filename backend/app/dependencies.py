import logging
from typing import Optional

from fastapi import Depends, HTTPException, Header, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> dict:
    """Extract and validate JWT from the Authorization header.

    In development mode without a token, returns a dev user.
    All tokens (dev or prod) are verified with the Supabase JWT secret.
    """
    settings = get_settings()

    # Dev mode: allow requests without auth header
    if settings.ENVIRONMENT == "development" and not authorization:
        return {"user_id": "dev-user-001", "claims": {}}

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )

    try:
        from jose import jwt, JWTError

        # Use the Supabase JWT secret for signature verification.
        # Falls back to unverified claims ONLY in development when no secret is set.
        jwt_secret = settings.SUPABASE_KEY
        if jwt_secret:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        elif settings.ENVIRONMENT == "development":
            # Dev-only fallback: accept unsigned tokens when no secret configured
            logger.warning("No SUPABASE_KEY set — accepting unverified JWT in dev mode")
            payload = jwt.get_unverified_claims(token)
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server misconfiguration: JWT secret not set",
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'sub' claim",
            )
        return {"user_id": user_id, "claims": payload}

    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during token validation")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )


async def get_supabase():
    return None


async def get_listing_db(request: Request):
    """Return the ListingDB instance from app state. May be None."""
    return getattr(request.app.state, "db", None)


async def get_db():
    yield None
