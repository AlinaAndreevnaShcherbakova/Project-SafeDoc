from app.api.access_service_router import router
from app.apps.factory import build_service_app

app = build_service_app(title="SafeDoc AccessControlService", router=router)
