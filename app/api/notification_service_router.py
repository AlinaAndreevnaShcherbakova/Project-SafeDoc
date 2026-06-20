from fastapi import APIRouter

from app.api.routes import notification

router = APIRouter()
router.include_router(notification.router, prefix="/internal/notifications", tags=["notifications"])
