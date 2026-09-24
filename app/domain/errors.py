"""Domain errors. Each carries a stable code and the HTTP status the API maps it to."""

from collections.abc import Iterable


class DomainError(Exception):
    code: str = "DOMAIN_ERROR"
    http_status: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UserNotFoundError(DomainError):
    code = "USER_NOT_FOUND"
    http_status = 404

    def __init__(self, username: str) -> None:
        super().__init__(f"User '{username}' not found")


class UserAlreadyExistsError(DomainError):
    code = "USER_ALREADY_EXISTS"
    http_status = 409

    def __init__(self, username: str) -> None:
        super().__init__(f"User '{username}' already exists")


class UnknownActionError(DomainError):
    code = "UNKNOWN_ACTION"
    http_status = 422

    def __init__(self, action: str, available: Iterable[str]) -> None:
        names = ", ".join(sorted(available))
        super().__init__(f"Unknown action '{action}'. Available: {names}")


class InvalidTaskParamsError(DomainError):
    code = "INVALID_TASK_PARAMS"
    http_status = 422

    def __init__(self, action: str, details: str) -> None:
        super().__init__(f"Invalid params for action '{action}': {details}")
