"""
The 'live operational lookup' tool — queries current incident state,
distinct from static runbook retrieval. This is what LangGraph's router
chooses when a question needs current data ("is INC-104 still open")
rather than documented policy ("what does the runbook recommend").
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident


async def get_incident_status(db: AsyncSession, incident_id: str | None = None, title_contains: str | None = None) -> dict:
    stmt = select(Incident)
    if incident_id:
        stmt = stmt.where(Incident.id == incident_id)
    elif title_contains:
        stmt = stmt.where(Incident.title.ilike(f"%{title_contains}%"))
    else:
        stmt = stmt.where(Incident.status == "open")

    result = await db.execute(stmt.order_by(Incident.created_at.desc()).limit(5))
    incidents = result.scalars().all()

    if not incidents:
        return {"found": False, "incidents": []}

    return {
        "found": True,
        "incidents": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "status": i.status,
                "last_deploy": i.last_deploy,
                "created_at": i.created_at.isoformat(),
            }
            for i in incidents
        ],
    }
