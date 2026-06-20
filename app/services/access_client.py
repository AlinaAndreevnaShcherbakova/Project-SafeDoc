import httpx

from app.core.config import settings


async def get_document_permissions(document_id: int, user_id: int) -> dict[str, bool]:
    #DocumentService получает итоговые права у AccessControlService через внутренний HTTP-вызов.
    base_url = settings.access_control_service_url or ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/access/internal/documents/{document_id}/permissions",
            headers={"X-Internal-Token": settings.internal_service_token},
            params={"user_id": user_id},
        )
        response.raise_for_status()
        return response.json()


async def get_documents_permissions(document_ids: list[int], user_id: int) -> dict[int, dict[str, bool]]:
    if not document_ids:
        return {}

    base_url = settings.access_control_service_url or ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/access/internal/documents/permissions/bulk",
            headers={"X-Internal-Token": settings.internal_service_token},
            json={"user_id": user_id, "document_ids": document_ids},
        )
        response.raise_for_status()
        payload = response.json()
        return {int(document_id): permissions for document_id, permissions in payload.items()}
