from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth_service_router import router
from app.apps.factory import build_service_app
from app.db.init_db import create_schema, seed_defaults
from app.db.postgres import SessionLocal, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_schema(engine)
    async with SessionLocal() as session:
        await seed_defaults(session)
    yield


app = build_service_app(title="SafeDoc AuthService", router=router, lifespan=lifespan)
