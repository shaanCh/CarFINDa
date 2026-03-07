from fastapi import Depends, HTTPException, Header, status
from jose import jwt, JWTError
from typing import Optional


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> dict:
    """Extract and validate JWT from the Authorization header.

    Stub implementation: decodes the JWT **without** verification so that
    development can proceed before the real Supabase JWT secret is wired in.
    Returns a dict with at least ``user_id``.

    TODO: Verify the JWT signature against the Supabase JWT secret.
    """
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
        # TODO: Replace with verified decode using Supabase JWT secret
        payload = jwt.get_unverified_claims(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'sub' claim",
            )
        return {"user_id": user_id, "claims": payload}
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )


async def get_supabase():
    """Return a Supabase client instance.

    TODO: Initialise and return a real ``supabase.Client`` using
    ``Settings.SUPABASE_URL`` and ``Settings.SUPABASE_SERVICE_ROLE_KEY``.
    """
    return None


async def get_db():
    """Yield an async database session.

    TODO: Create an async SQLAlchemy / asyncpg session bound to
    ``Settings.DATABASE_URL`` (Supabase Postgres direct connection).
    """
    yield None
