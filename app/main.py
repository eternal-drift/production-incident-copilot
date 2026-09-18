import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.rate_limit import limiter
from app.routers import chat, health, incidents
from app.telemetry import setup_telemetry

# Real, pre-existing gap found in Session 20 (Phase 3, RAG hardening spec):
# app/routers/chat.py's "incident_copilot.audit" logger (added in Session 7
# for docs/threat-model.md Finding #7) had never actually emitted anything
# in any prior session -- nothing in this app ever called
# logging.basicConfig() or attached a handler, so its INFO records had
# nowhere to go and were silently dropped. Caught by trying to verify Phase
# 3's own definition of done ("the distinction is visible in logs") against
# the real running container and finding zero output, not by code review.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Rate limiting -- closes docs/threat-model.md Finding #4 (no rate limiting
# anywhere; combined with no auth, /chat was unlimited, unmetered LLM
# compute for any caller). Keyed by client IP since there's no per-identity
# auth (single shared API key, see app/auth.py) to key on instead.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

setup_telemetry(app)

app.include_router(health.router)
app.include_router(incidents.router)
app.include_router(chat.router)


@app.get("/")
async def root():
    return {"service": settings.app_name, "environment": settings.environment}
