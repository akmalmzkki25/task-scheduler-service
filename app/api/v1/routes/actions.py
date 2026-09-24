from fastapi import APIRouter

from app.api.deps import RegistryDep
from app.schemas.action import ActionOut
from app.schemas.common import ApiResponse, ok

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("")
async def list_actions(registry: RegistryDep) -> ApiResponse[list[ActionOut]]:
    return ok([ActionOut.from_strategy(s) for s in registry.all()])
