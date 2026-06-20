from fastapi import APIRouter

from app.api.routes import access

router = APIRouter()
router.include_router(access.router, prefix="/access", tags=["access"])
