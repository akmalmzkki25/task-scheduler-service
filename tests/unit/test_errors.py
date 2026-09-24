import pytest

from app.domain.errors import (
    DomainError,
    InvalidTaskError,
    InvalidTaskParamsError,
    UnknownActionError,
    UserAlreadyExistsError,
    UserNotFoundError,
)


@pytest.mark.parametrize(
    ("error", "code", "status", "message"),
    [
        (UserNotFoundError("carol"), "USER_NOT_FOUND", 404, "User 'carol' not found"),
        (
            UserAlreadyExistsError("alice"),
            "USER_ALREADY_EXISTS",
            409,
            "User 'alice' already exists",
        ),
        (
            UnknownActionError("archive", ["sync", "delete", "backup"]),
            "UNKNOWN_ACTION",
            422,
            "Unknown action 'archive'. Available: backup, delete, sync",
        ),
        (
            InvalidTaskParamsError("sync", "target: Field required"),
            "INVALID_TASK_PARAMS",
            422,
            "Invalid params for action 'sync': target: Field required",
        ),
        (
            InvalidTaskError("time: String should match pattern"),
            "INVALID_TASK",
            422,
            "Invalid task: time: String should match pattern",
        ),
    ],
)
def test_domain_errors_carry_code_status_and_message(
    error: DomainError, code: str, status: int, message: str
) -> None:
    assert isinstance(error, DomainError)
    assert error.code == code
    assert error.http_status == status
    assert error.message == message
    assert str(error) == message
