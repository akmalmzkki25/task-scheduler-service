"""Base class for action strategies.

Each action (sync, backup, delete, ...) is one subclass with its own parameter model.
The executor only talks to this interface, so adding an action never touches it.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.domain.errors import InvalidTaskParamsError

logger = logging.getLogger("app.strategies")


def require_absolute_path(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError("must be an absolute path starting with '/'")
    return value


class TargetParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str

    @field_validator("target")
    @classmethod
    def _check_target(cls, value: str) -> str:
        return require_absolute_path(value)


def format_validation_error(exc: ValidationError) -> str:
    """Turn a Pydantic error into `field: reason; field: reason`."""
    parts = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) or "params"
        parts.append(f"{field}: {error['msg']}")
    return "; ".join(parts)


class ActionStrategy[P: BaseModel](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    params_model: type[P]

    def __init__(self, simulated_latency: float = 0.1) -> None:
        self.simulated_latency = simulated_latency

    def parse_params(self, raw: Mapping[str, Any]) -> P:
        try:
            return self.params_model.model_validate(dict(raw))
        except ValidationError as exc:
            raise InvalidTaskParamsError(self.name, format_validation_error(exc)) from exc

    async def execute(self, params: P) -> str:
        """Run the simulated action and return a human-readable result message."""
        await asyncio.sleep(self.simulated_latency)
        message = self.describe(params)
        logger.info(message)
        return message

    @abstractmethod
    def describe(self, params: P) -> str:
        """Return the `[SIMULATED] ...` line for this action. No side effects."""
