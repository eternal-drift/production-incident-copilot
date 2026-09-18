"""
Two tables sharing one Postgres instance — the core architectural
trade-off of this project (single DB for transactional + vector data,
vs. a dedicated vector store). See docs/adr/0001-single-postgres.md.
"""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="sev3")  # sev1|sev2|sev3
    status: Mapped[str] = mapped_column(String(20), default="open")    # open|mitigated|resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deploy: Mapped[str] = mapped_column(String(200), default="")  # free-text: "v2.4.1 @ 2026-08-20T09:00Z"


class RunbookChunk(Base):
    __tablename__ = "runbook_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_document: Mapped[str] = mapped_column(String(200), nullable=False)
    section: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(settings.embedding_dim))

    # Postgres-native full-text search column (ADR 0002) -- generated/stored
    # by Postgres itself from `content`, not maintained app-side, so it can
    # never drift out of sync with an edited chunk.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
    )

    __table_args__ = (
        Index("ix_runbook_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )
