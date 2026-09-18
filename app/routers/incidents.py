from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.post_incident import generate_review
from app.auth import require_api_key
from app.config import settings
from app.database import get_db
from app.models import Incident
from app.rate_limit import limiter
from app.schemas import IncidentCreate, IncidentOut, IncidentReviewRequest, IncidentReviewResponse

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentOut, status_code=201)
@limiter.limit(settings.rate_limit_incidents)
async def create_incident(request: Request, payload: IncidentCreate, db: AsyncSession = Depends(get_db), _: None = Depends(require_api_key)):
    incident = Incident(**payload.model_dump())
    db.add(incident)
    await db.commit()
    await db.refresh(incident)
    return incident


@router.get("", response_model=list[IncidentOut])
@limiter.limit(settings.rate_limit_incidents)
async def list_incidents(request: Request, db: AsyncSession = Depends(get_db), _: None = Depends(require_api_key)):
    result = await db.execute(select(Incident).order_by(Incident.created_at.desc()))
    return result.scalars().all()


@router.get("/{incident_id}", response_model=IncidentOut)
@limiter.limit(settings.rate_limit_incidents)
async def get_incident(request: Request, incident_id: str, db: AsyncSession = Depends(get_db), _: None = Depends(require_api_key)):
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/{incident_id}/review", response_model=IncidentReviewResponse)
@limiter.limit(settings.rate_limit_chat)  # same cost profile as /chat -- one LLM call
async def review_incident(
    request: Request,
    incident_id: str,
    payload: IncidentReviewRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
):
    """Generate a post-incident review DRAFT. Never authoritative -- see
    app/ai/post_incident.py for why the LLM drafts and a human decides."""
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    review = await generate_review(db, incident, additional_context=payload.additional_context)
    return IncidentReviewResponse(incident_id=incident_id, **review)
