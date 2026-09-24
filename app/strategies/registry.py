"""Maps action names to strategy instances."""

from typing import Any

from app.domain.errors import UnknownActionError
from app.strategies.backup import BackupStrategy
from app.strategies.base import ActionStrategy
from app.strategies.delete import DeleteStrategy
from app.strategies.sync import SyncStrategy

type AnyStrategy = ActionStrategy[Any]


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, AnyStrategy] = {}

    def register(self, strategy: AnyStrategy) -> None:
        if strategy.name in self._strategies:
            raise ValueError(f"Action '{strategy.name}' is already registered")
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> AnyStrategy:
        try:
            return self._strategies[name]
        except KeyError:
            raise UnknownActionError(name, self._strategies) from None

    def names(self) -> list[str]:
        return sorted(self._strategies)

    def all(self) -> list[AnyStrategy]:
        return [self._strategies[name] for name in self.names()]


def build_default_registry(simulated_latency: float) -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy_cls in (SyncStrategy, BackupStrategy, DeleteStrategy):
        registry.register(strategy_cls(simulated_latency))
    return registry
