from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user
from app.models.schemas import UserPreferences

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("/", response_model=UserPreferences)
async def get_preferences(
    user: dict = Depends(get_current_user),
):
    """Return the authenticated user's saved vehicle preferences.

    TODO: Fetch from the ``user_preferences`` table in Supabase.
    """
    # Stub: return empty/default preferences
    return UserPreferences()


@router.put("/", response_model=UserPreferences)
async def update_preferences(
    prefs: UserPreferences,
    user: dict = Depends(get_current_user),
):
    """Create or replace the authenticated user's preferences.

    TODO: Upsert into the ``user_preferences`` table keyed by user_id.
    """
    # Stub: echo back the submitted preferences
    return prefs
