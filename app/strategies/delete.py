from app.strategies.base import ActionStrategy, TargetParams


class DeleteStrategy(ActionStrategy[TargetParams]):
    """Logs the deletion only. It must never remove anything from the filesystem."""

    name = "delete"
    description = "Delete the target path (simulated, nothing is removed)."
    params_model = TargetParams

    def describe(self, params: TargetParams) -> str:
        return f"[SIMULATED] delete {params.target}"
