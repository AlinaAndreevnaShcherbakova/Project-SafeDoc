from app.api.notification_service_router import router
from app.apps.factory import build_service_app

app = build_service_app(title="SafeDoc NotificationService", router=router)
