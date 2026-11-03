"""Optional API-key protection.

If `API_KEY` is set in the environment every `/api` route requires it, either
in the `X-API-Key` header or as an `api_key` query parameter (the latter is
needed for <img>/<video> tags that cannot send headers, e.g. the MJPEG stream).
If `API_KEY` is empty the API is open — suitable for a LAN/edge deployment.
"""
import secrets

from fastapi import HTTPException, Request, status

from app.core.config import settings


async def require_api_key(request: Request) -> None:
    if not settings.API_KEY:
        return
    supplied = request.headers.get("x-api-key") or request.query_params.get("api_key") or ""
    if not secrets.compare_digest(supplied, settings.API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
