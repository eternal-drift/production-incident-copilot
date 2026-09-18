from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    severity: str = Field(default="sev3", pattern="^(sev1|sev2|sev3)$")
    last_deploy: str = ""


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: str
    severity: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]
    last_deploy: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Source(BaseModel):
    document: str
    section: str


class ChatResponse(BaseModel):
    answer: str
    decision: str  # DOCUMENT | LIVE | ESCALATE
    confidence: float
    sources: list[Source] = []
    escalate: bool


class IncidentReviewRequest(BaseModel):
    additional_context: str = Field(default="", max_length=4000)


class IncidentReviewResponse(BaseModel):
    incident_id: str
    draft: str
    disclaimer: str
    sources: list[Source] = []
