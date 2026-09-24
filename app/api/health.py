import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import ContainerDep

logger = logging.getLogger("app.api")
router = APIRouter(tags=["health"])


@router.get("/health")
async def health(container: ContainerDep) -> JSONResponse:
    components = {"postgres": "ok", "redis": "ok"}
    try:
        async with container.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: Postgres unavailable")
        components["postgres"] = "unavailable"
    try:
        await container.quota.ping()
    except Exception:
        logger.exception("Health check: Redis unavailable")
        components["redis"] = "unavailable"

    healthy = all(state == "ok" for state in components.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "components": components},
    )
