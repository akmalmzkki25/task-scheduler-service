from fastapi import APIRouter

from app.api.v1.routes import actions, executions, scheduler, tasks, users

api_router = APIRouter(prefix="/api/v1")
for module in (users, actions, tasks, scheduler, executions):
    api_router.include_router(module.router)
