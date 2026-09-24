"""The response envelope every /api/v1 endpoint returns."""

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    error_id: str | None = None


class PageMeta(BaseModel):
    total: int
    page: int
    limit: int


class ApiResponse[T](BaseModel):
    success: bool
    data: T | None = None
    error: ErrorBody | None = None
    meta: PageMeta | None = None


def ok[T](data: T, meta: PageMeta | None = None) -> ApiResponse[T]:
    return ApiResponse[T](success=True, data=data, meta=meta)


def error_payload(code: str, message: str, error_id: str | None = None) -> dict[str, Any]:
    body = ApiResponse[None](
        success=False, error=ErrorBody(code=code, message=message, error_id=error_id)
    )
    return body.model_dump(mode="json")
