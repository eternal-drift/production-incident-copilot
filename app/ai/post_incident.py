"""
Post-incident review draft generation (Phase 8, project plan). Generates a
structured DRAFT from incident data + grounded runbook context -- never an
authoritative RCA. Same governance posture as the rest of this project:
the LLM drafts, it does not decide, and the output is explicitly marked
for human review rather than presented as a finished analysis. Nothing
here is persisted or auto-applied to the runbook corpus -- an LLM must
never be the one to determine root cause on its own.
"""
from app.ai.llm_client import LLMClient
from app.ai.rag import retrieve
from app.models import Incident
from sqlalchemy.ext.asyncio import AsyncSession

REVIEW_SECTIONS = [
    "Incident Summary", "Impact", "Timeline", "Detection",
    "Root Cause / Contributing Factors", "Resolution", "What Worked",
    "What Did Not", "Runbook Gap", "Corrective Actions",
    "Suggested Runbook Update",
]

DRAFT_DISCLAIMER = (
    "DRAFT — generated for human review. This is NOT an authoritative root "
    "cause analysis. Root cause, contributing factors, and corrective "
    "actions must be verified and approved by the incident owner before "
    "being treated as fact or acted upon. VERIFY EVERY SPECIFIC CLAIM: "
    "despite explicit instructions not to invent details, live testing "
    "showed this generator can still fabricate plausible-looking specifics "
    "(e.g. exact timestamps, alert names) that were never in the provided "
    "input -- treat any detail you don't recognize as unverified, not as "
    "sourced fact, especially in Timeline and Detection."
)


async def generate_review(db: AsyncSession, incident: Incident, additional_context: str = "") -> dict:
    # Ground the draft in the same runbook corpus /chat uses -- a
    # post-incident review that cites real runbook sections is more
    # defensible than one invented from the incident title alone.
    query = f"{incident.title}. {incident.description}".strip()
    retrieval = await retrieve(db, query) if query else {"strong_chunks": [], "confidence": 0.0}
    context = "\n\n".join(
        f"[{c['source']} / {c['section']}] {c['content']}" for c in retrieval["strong_chunks"]
    )

    incident_facts = (
        f"Title: {incident.title}\n"
        f"Severity: {incident.severity}\n"
        f"Status: {incident.status}\n"
        f"Created: {incident.created_at.isoformat()}\n"
        f"Resolved: {incident.resolved_at.isoformat() if incident.resolved_at else 'not resolved'}\n"
        f"Last deploy before incident: {incident.last_deploy or 'unknown'}\n"
        f"Description: {incident.description or 'none provided'}"
    )

    system = (
        "You are drafting a post-incident review for human review — NOT an authoritative "
        "root cause analysis. Use ONLY the incident facts and runbook context provided below; "
        "never invent timeline events, actions taken, or root causes not supported by the "
        "input. Where information is missing, write 'Not provided — requires input from "
        "incident responders' rather than guessing. Produce exactly these sections, in this "
        "order, as markdown headers: " + ", ".join(REVIEW_SECTIONS) + ". "
        "Every claim in Root Cause / Contributing Factors must be phrased as a hypothesis for "
        "human verification (e.g. 'may be attributable to...'), never stated as settled fact."
    )
    prompt = (
        f"Incident facts:\n{incident_facts}\n\n"
        f"Additional context from responder (may be empty):\n{additional_context or 'none provided'}\n\n"
        f"Relevant runbook context:\n{context or 'no relevant runbook content retrieved'}\n\n"
        "Draft the post-incident review now."
    )

    llm = LLMClient()
    try:
        draft = llm.generate(prompt, system=system)
    except Exception as e:
        draft = (
            f"[LLM unavailable: {e}] Unable to generate a draft narrative. Grounded inputs "
            f"below are available for a human-authored review instead.\n\n{incident_facts}\n\n{context}"
        )

    return {
        "draft": draft,
        "disclaimer": DRAFT_DISCLAIMER,
        "sources": [{"document": c["source"], "section": c["section"]} for c in retrieval["strong_chunks"]],
    }
