from app.strategies.base import ActionStrategy, TargetParams


class SyncStrategy(ActionStrategy[TargetParams]):
    name = "sync"
    description = "Synchronize the target path (simulated)."
    params_model = TargetParams

    def describe(self, params: TargetParams) -> str:
        return f"[SIMULATED] sync {params.target}"
