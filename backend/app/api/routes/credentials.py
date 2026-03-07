"""
Credentials Routes — Secure storage and management of platform credentials.

Users submit their Facebook (or other platform) credentials via these endpoints.
Credentials are encrypted at rest and used by the browser agent to log in
and perform actions on the user's behalf.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.services.credentials import CredentialService
from app.services.browser.agent import BrowserAgent
from app.services.scraping.browser_client import BrowserClient
from app.config import get_settings

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


class CredentialInput(BaseModel):
    platform: str = "facebook"
    email: str
    password: str


class TwoFAInput(BaseModel):
    code: str


class CredentialResponse(BaseModel):
    platform: str
    login_status: str
    is_active: bool


class LoginResult(BaseModel):
    success: bool
    login_status: str
    needs_2fa: bool = False
    message: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def store_credentials(
    body: CredentialInput,
    user: dict = Depends(get_current_user),
):
    """Store encrypted platform credentials.

    Credentials are encrypted with Fernet symmetric encryption before storage.
    The encryption key is derived from the server's service role key.
    """
    cred_service = CredentialService()
    try:
        result = await cred_service.store_credentials(
            user_id=user["user_id"],
            platform=body.platform,
            email=body.email,
            password=body.password,
        )
        return CredentialResponse(**result)
    finally:
        await cred_service.close()


@router.post("/login", response_model=LoginResult)
async def login_to_platform(
    body: CredentialInput,
    user: dict = Depends(get_current_user),
):
    """Store credentials AND immediately attempt to log in via the browser agent.

    This is the main flow:
    1. Encrypt and store credentials
    2. Launch browser agent to log into the platform
    3. Return login status (success, failed, or needs_2fa)
    """
    settings = get_settings()
    cred_service = CredentialService()

    try:
        # Store credentials first
        await cred_service.store_credentials(
            user_id=user["user_id"],
            platform=body.platform,
            email=body.email,
            password=body.password,
        )

        # Launch browser agent to log in
        browser = BrowserClient(
            base_url=settings.SIDECAR_URL,
            token=settings.SIDECAR_TOKEN,
        )
        agent = BrowserAgent(
            browser=browser,
            profile=f"carfinda-{user['user_id'][:8]}-{body.platform}",
        )

        result = await agent.run(
            task=f"Log into {body.platform.title()}. Navigate to the login page, enter the email and password, and submit the form.",
            context={
                "email": body.email,
                "password": body.password,
                "platform": body.platform,
                "login_url": _login_url(body.platform),
            },
        )

        # Determine status
        needs_2fa = result.get("needs_input", {}).get("input_type") == "2fa" if result.get("needs_input") else False
        if result["success"]:
            login_status = "success"
        elif needs_2fa:
            login_status = "requires_2fa"
        else:
            login_status = "failed"

        await cred_service.update_login_status(user["user_id"], body.platform, login_status)
        await browser.close()

        return LoginResult(
            success=result["success"],
            login_status=login_status,
            needs_2fa=needs_2fa,
            message=result.get("result"),
        )

    finally:
        await cred_service.close()


@router.post("/2fa", response_model=LoginResult)
async def submit_2fa(
    body: TwoFAInput,
    platform: str = "facebook",
    user: dict = Depends(get_current_user),
):
    """Submit a 2FA code to complete a pending login."""
    settings = get_settings()

    browser = BrowserClient(
        base_url=settings.SIDECAR_URL,
        token=settings.SIDECAR_TOKEN,
    )
    agent = BrowserAgent(
        browser=browser,
        profile=f"carfinda-{user['user_id'][:8]}-{platform}",
    )

    result = await agent.resume(
        task=f"Complete the {platform.title()} login by entering the 2FA code.",
        user_input=body.code,
        context={"platform": platform},
    )

    cred_service = CredentialService()
    try:
        status_str = "success" if result["success"] else "failed"
        await cred_service.update_login_status(user["user_id"], platform, status_str)
    finally:
        await cred_service.close()

    await browser.close()

    return LoginResult(
        success=result["success"],
        login_status="success" if result["success"] else "failed",
        message=result.get("result"),
    )


@router.get("/{platform}")
async def get_credential_status(
    platform: str,
    user: dict = Depends(get_current_user),
):
    """Check if credentials are stored and their login status."""
    cred_service = CredentialService()
    try:
        creds = await cred_service.get_credentials(user["user_id"], platform)
        if not creds:
            return {"has_credentials": False, "login_status": None}
        return {
            "has_credentials": True,
            "login_status": creds["login_status"],
            "last_login_at": creds.get("last_login_at"),
        }
    finally:
        await cred_service.close()


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    platform: str,
    user: dict = Depends(get_current_user),
):
    """Delete stored credentials for a platform."""
    cred_service = CredentialService()
    try:
        await cred_service.delete_credentials(user["user_id"], platform)
    finally:
        await cred_service.close()


def _login_url(platform: str) -> str:
    """Get the login URL for a platform."""
    urls = {
        "facebook": "https://www.facebook.com/login",
        "craigslist": "https://accounts.craigslist.org/login",
    }
    return urls.get(platform, "")
