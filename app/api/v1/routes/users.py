from fastapi import APIRouter, status

from app.api.deps import TzDep, UserServiceDep
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UsageOut, UserCreate, UserOut, UserWithUsageOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_user(body: UserCreate, users: UserServiceDep, tz: TzDep) -> ApiResponse[UserOut]:
    user = await users.register(body.username, body.daily_quota)
    return ok(UserOut.from_domain(user, tz))


@router.get("/{username}")
async def get_user(
    username: str, users: UserServiceDep, tz: TzDep
) -> ApiResponse[UserWithUsageOut]:
    user, used, day = await users.get_usage_today(username)
    base = UserOut.from_domain(user, tz)
    usage = UsageOut(date=day, used=used, limit=user.daily_quota)
    return ok(UserWithUsageOut(**base.model_dump(), usage_today=usage))
