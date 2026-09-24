from typing import Any

from pydantic import BaseModel

from app.strategies.base import ActionStrategy


class ActionOut(BaseModel):
    name: str
    description: str
    params_schema: dict[str, Any]

    @classmethod
    def from_strategy(cls, strategy: ActionStrategy[Any]) -> "ActionOut":
        return cls(
            name=strategy.name,
            description=strategy.description,
            params_schema=strategy.params_model.model_json_schema(),
        )
