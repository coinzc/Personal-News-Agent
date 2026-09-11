from datetime import date

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.post("/generate")
async def generate_digest(request: Request, digest_date: date | None = None) -> dict[str, object]:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Digest service is not configured")
    digest = await container.generate_daily_digest(digest_date)
    return {"id": str(digest.id), "date": digest.digest_date.isoformat(), "status": digest.status}
