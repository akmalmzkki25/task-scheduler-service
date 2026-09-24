from pydantic import field_validator

from app.strategies.base import ActionStrategy, TargetParams, require_absolute_path


class BackupParams(TargetParams):
    destination: str | None = None

    @field_validator("destination")
    @classmethod
    def _check_destination(cls, value: str | None) -> str | None:
        return None if value is None else require_absolute_path(value)


class BackupStrategy(ActionStrategy[BackupParams]):
    name = "backup"
    description = "Back up the target path to an optional destination (simulated)."
    params_model = BackupParams

    def describe(self, params: BackupParams) -> str:
        return f"[SIMULATED] backup {params.target} -> {params.destination or '<default>'}"
