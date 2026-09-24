import logging
from typing import Any

import pytest

from app.domain.errors import InvalidTaskParamsError, UnknownActionError
from app.strategies.backup import BackupStrategy
from app.strategies.base import TargetParams
from app.strategies.delete import DeleteStrategy
from app.strategies.registry import StrategyRegistry, build_default_registry
from app.strategies.sync import SyncStrategy


@pytest.mark.parametrize(
    ("strategy", "params", "expected"),
    [
        (SyncStrategy(0), {"target": "/data/x"}, "[SIMULATED] sync /data/x"),
        (DeleteStrategy(0), {"target": "/tmp/z"}, "[SIMULATED] delete /tmp/z"),
        (
            BackupStrategy(0),
            {"target": "/srv/y", "destination": "/backups/y"},
            "[SIMULATED] backup /srv/y -> /backups/y",
        ),
        (BackupStrategy(0), {"target": "/srv/y"}, "[SIMULATED] backup /srv/y -> <default>"),
    ],
)
async def test_strategy_returns_and_logs_simulated_message(
    strategy: SyncStrategy,
    params: dict[str, Any],
    expected: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parsed = strategy.parse_params(params)

    with caplog.at_level(logging.INFO, logger="app.strategies"):
        message = await strategy.execute(parsed)

    assert message == expected
    assert expected in caplog.messages


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({}, "target: Field required"),
        ({"target": "data/x"}, "target: Value error, must be an absolute path"),
        ({"target": ""}, "target: Value error, must be an absolute path"),
        ({"target": "/data/x", "mode": "fast"}, "mode: Extra inputs are not permitted"),
    ],
)
def test_parse_params_rejects_bad_input(params: dict[str, Any], fragment: str) -> None:
    with pytest.raises(InvalidTaskParamsError) as info:
        SyncStrategy(0).parse_params(params)

    assert info.value.message.startswith("Invalid params for action 'sync': ")
    assert fragment in info.value.message


def test_parse_params_rejects_relative_backup_destination() -> None:
    with pytest.raises(InvalidTaskParamsError, match="destination"):
        BackupStrategy(0).parse_params({"target": "/srv/y", "destination": "backups"})


def test_parse_params_returns_typed_model() -> None:
    parsed = SyncStrategy(0).parse_params({"target": "/data/x"})

    assert isinstance(parsed, TargetParams)
    assert parsed.target == "/data/x"


def test_default_registry_lists_actions_sorted() -> None:
    registry = build_default_registry(simulated_latency=0)

    assert registry.names() == ["backup", "delete", "sync"]
    assert [s.name for s in registry.list()] == ["backup", "delete", "sync"]
    assert isinstance(registry.get("sync"), SyncStrategy)


def test_registry_get_unknown_action_lists_available() -> None:
    registry = build_default_registry(simulated_latency=0)

    with pytest.raises(UnknownActionError, match="Available: backup, delete, sync"):
        registry.get("archive")


def test_registry_rejects_duplicate_names() -> None:
    registry = StrategyRegistry()
    registry.register(SyncStrategy(0))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(SyncStrategy(0))
