"""
API key auth. Closes docs/threat-model.md Finding #1 (no auth on any
endpoint -- confirmed live: GET /incidents returned the full incident
list with zero credentials). A single shared key is the right level of
effort for this prototype's actual threat model (see the doc for why);
a real deployment needs per-identity credentials (OAuth2/OIDC), not just
a stronger version of a shared secret.
"""
from fastapi import Header, HTTPException

from app.config import settings


async def require_api_key(x_api_key: str = Header(...)) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
