import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.models.schemas import MonitorRequest, MonitorResponse

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.post(
    "/",
    response_model=MonitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_monitor(
    request: MonitorRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new monitoring watch that periodically re-runs a search.

    TODO: Persist the monitor config in the database and register a
    scheduled task (e.g. via Celery beat or a cron-style scheduler).
    """
    monitor_id = str(uuid.uuid4())

    return MonitorResponse(
        monitor_id=monitor_id,
        preferences_snapshot=request.preferences_snapshot,
        frequency=request.frequency,
        status="active",
        created_at=datetime.now(timezone.utc),
    )


@router.get("/", response_model=list[MonitorResponse])
async def list_monitors(
    user: dict = Depends(get_current_user),
):
    """List all active monitors for the authenticated user.

    TODO: Query the ``monitors`` table filtered by user_id.
    """
    # Stub: return an empty list
    return []


@router.delete(
    "/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_monitor(
    monitor_id: str,
    user: dict = Depends(get_current_user),
):
    """Cancel (soft-delete) an active monitor.

    TODO: Mark the monitor as cancelled in the database and
    de-register its scheduled task.
    """
    # TODO: Look up monitor by id; return 404 if not found or not owned by user
    return None
