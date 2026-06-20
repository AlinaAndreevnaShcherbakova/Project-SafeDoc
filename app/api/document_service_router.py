from fastapi import APIRouter

from app.api.routes import documents, public_links

router = APIRouter()
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(public_links.router, prefix="/links", tags=["links"])
