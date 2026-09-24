from fastapi import APIRouter

from app.api.deps import ExecutionsDep, PaginationDep, TzDep
from app.domain.models import ExecutionStatus
from app.schemas.common import ApiResponse, PageMeta, ok
from app.schemas.execution import ExecutionOut

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("")
async def list_executions(
    executions: ExecutionsDep,
    tz: TzDep,
    page: PaginationDep,
    user: str | None = None,
    status: ExecutionStatus | None = None,
) -> ApiResponse[list[ExecutionOut]]:
    items, total = await executions.list_page(user, status, page.offset, page.limit)
    return ok(
        [ExecutionOut.from_domain(r, tz) for r in items],
        PageMeta(total=total, page=page.page, limit=page.limit),
    )
