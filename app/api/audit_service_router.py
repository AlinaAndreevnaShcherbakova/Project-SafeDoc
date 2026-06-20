from fastapi import APIRouter

from app.api.routes import audit

router = APIRouter()
router.include_router(audit.router, prefix="/audit", tags=["audit"])
