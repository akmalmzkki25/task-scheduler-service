"""FastAPI dependency providers. Tests override these through `app.dependency_overrides`."""

from dataclasses import dataclass
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Query, Request

from app.api.container import AppContainer
from app.repositories.interfaces import ExecutionRepository
from app.services.scheduler import Scheduler
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.strategies.registry import StrategyRegistry

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_user_service(container: ContainerDep) -> UserService:
    return container.user_service


def get_task_service(container: ContainerDep) -> TaskService:
    return container.task_service


def get_scheduler(container: ContainerDep) -> Scheduler:
    return container.scheduler


def get_registry(container: ContainerDep) -> StrategyRegistry:
    return container.registry


def get_executions(container: ContainerDep) -> ExecutionRepository:
    return container.executions


def get_tz(container: ContainerDep) -> ZoneInfo:
    return container.settings.tz


@dataclass(frozen=True)
class Pagination:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    return Pagination(page=page, limit=limit)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
SchedulerDep = Annotated[Scheduler, Depends(get_scheduler)]
RegistryDep = Annotated[StrategyRegistry, Depends(get_registry)]
ExecutionsDep = Annotated[ExecutionRepository, Depends(get_executions)]
TzDep = Annotated[ZoneInfo, Depends(get_tz)]
PaginationDep = Annotated[Pagination, Depends(get_pagination)]
