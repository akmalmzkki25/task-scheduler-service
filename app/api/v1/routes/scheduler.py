from fastapi import APIRouter

from app.api.deps import SchedulerDep, TzDep
from app.schemas.common import ApiResponse, ok
from app.schemas.execution import TickReportOut

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.post("/tick")
async def run_tick(scheduler: SchedulerDep, tz: TzDep) -> ApiResponse[TickReportOut]:
    """Run one scheduler tick now, in addition to the background loop."""
    report = await scheduler.tick()
    return ok(TickReportOut.from_domain(report, tz))
