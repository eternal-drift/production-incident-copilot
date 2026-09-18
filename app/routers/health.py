from fastapi import APIRouter
from sqlalchemy import text

from app.database import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness():
    return {"status": "alive"}


@router.get("/readyz")
async def readiness():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "db": "ok"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}
