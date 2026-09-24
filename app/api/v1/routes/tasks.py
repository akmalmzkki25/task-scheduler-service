from fastapi import APIRouter, status

from app.api.deps import PaginationDep, TaskServiceDep, TzDep
from app.schemas.common import ApiResponse, PageMeta, ok
from app.schemas.task import TaskCreate, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_task(body: TaskCreate, tasks: TaskServiceDep, tz: TzDep) -> ApiResponse[TaskOut]:
    task = await tasks.submit(body)
    return ok(TaskOut.from_domain(task, tz))


@router.get("")
async def list_tasks(
    tasks: TaskServiceDep, tz: TzDep, page: PaginationDep, user: str | None = None
) -> ApiResponse[list[TaskOut]]:
    items, total = await tasks.list_tasks(user, page=page.page, limit=page.limit)
    return ok(
        [TaskOut.from_domain(t, tz) for t in items],
        PageMeta(total=total, page=page.page, limit=page.limit),
    )
