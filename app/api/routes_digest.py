from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import require_admin_api_key
from app.services.news_query_service import SQLAlchemyNewsToolService

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/today")
async def get_today_digest(request: Request) -> dict[str, object]:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Digest service is not configured")
    target_date = datetime.now(ZoneInfo(container.settings.timezone)).date()
    async with container.session_factory() as session:
        digest = await SQLAlchemyNewsToolService(session).get_daily_digest(target_date)
    if digest is None:
        raise HTTPException(status_code=404, detail="Today's digest not found")
    return digest


@router.post("/generate")
async def generate_digest(
    request: Request,
    digest_date: date | None = None,
    _: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Digest service is not configured")
    digest = await container.generate_daily_digest(digest_date)
    return {"id": str(digest.id), "date": digest.digest_date.isoformat(), "status": digest.status}


@router.post("/send")
async def send_digest(
    request: Request,
    digest_date: date | None = None,
    _: None = Depends(require_admin_api_key),
) -> dict[str, object]:
    container = getattr(request.app.state, "container", None)
    if container is None or not container.delivery_available:
        raise HTTPException(status_code=503, detail="Digest delivery is not configured")
    sent = await container.send_daily_digest(digest_date)
    target_date = digest_date or datetime.now(ZoneInfo(container.settings.timezone)).date()
    return {"date": target_date.isoformat(), "sent": sent}
