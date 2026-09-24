"""End-to-end: a real uvicorn process, the real clock, and the background scheduler loop.

Nothing is faked. The test registers users, submits tasks for the next minute over
HTTP, then waits for the background loop to run them on its own. It checks quota
enforcement, the once-per-day rule, error envelopes, and the server's log output.

Run with: pytest -m e2e   (takes about a minute; it waits for the wall clock)
"""

import os
import socket
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.e2e

JAKARTA = ZoneInfo("Asia/Jakarta")
ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_S = 30
EXECUTION_TIMEOUT_S = 90
# Leave room so the submitted minute can't roll over while tasks are being created.
MIN_SECONDS_BEFORE_NEXT_MINUTE = 8


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_healthy(client: httpx.Client, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early with code {process.returncode}")
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    raise TimeoutError("Server did not become healthy in time")


@pytest.fixture
def server(
    engine: AsyncEngine,
    redis_client: object,
    test_database_url: str,
    test_redis_url: str,
    tmp_path: Path,
) -> Iterator[tuple[httpx.Client, Path]]:
    """Start the app against the test database with a 1-second tick interval."""
    port = free_port()
    log_path = tmp_path / "server.log"
    env = {
        **os.environ,
        "DATABASE_URL": test_database_url,
        "REDIS_URL": test_redis_url,
        "SCHEDULER_ENABLED": "true",
        "TICK_INTERVAL_SECONDS": "1",
        "SEED_DEMO_DATA": "false",
        "SIMULATED_LATENCY_SECONDS": "0.05",
        "TIMEZONE": "Asia/Jakarta",
        "LOG_LEVEL": "INFO",
    }
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
        try:
            wait_until_healthy(client, process)
            yield client, log_path
        finally:
            client.close()
            process.terminate()
            process.wait(timeout=10)


def next_minute_slot() -> datetime:
    """Return the start of the next minute, waiting first if it's too close."""
    now = datetime.now(JAKARTA)
    if now.second >= 60 - MIN_SECONDS_BEFORE_NEXT_MINUTE:
        time.sleep(60 - now.second + 1)
        now = datetime.now(JAKARTA)
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1)


def post(client: httpx.Client, path: str, body: dict[str, Any]) -> httpx.Response:
    return client.post(f"/api/v1{path}", json=body)


def wait_for_executions(client: httpx.Client, expected: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + EXECUTION_TIMEOUT_S
    while time.monotonic() < deadline:
        body = client.get("/api/v1/executions", params={"limit": 100}).json()
        if body["meta"]["total"] >= expected:
            data: list[dict[str, Any]] = body["data"]
            return data
        time.sleep(1)
    raise TimeoutError(f"Expected {expected} executions within {EXECUTION_TIMEOUT_S}s")


def test_daily_flow_runs_on_schedule_and_enforces_quota(
    server: tuple[httpx.Client, Path],
) -> None:
    client, log_path = server

    # Arrange: two users, alice with a quota smaller than her task count.
    assert post(client, "/users", {"username": "alice", "daily_quota": 2}).status_code == 201
    assert post(client, "/users", {"username": "bob", "daily_quota": 5}).status_code == 201

    slot = next_minute_slot()
    hhmm = slot.strftime("%H:%M")
    submissions = [
        {"user": "alice", "action": "sync", "params": {"target": "/data/x"}},
        {"user": "alice", "action": "delete", "params": {"target": "/tmp/z"}},
        {"user": "alice", "action": "sync", "params": {"target": "/data/extra"}},
        {"user": "bob", "action": "backup", "params": {"target": "/srv/y", "destination": "/bk"}},
    ]
    for item in submissions:
        response = post(client, "/tasks", {**item, "time": hhmm})
        assert response.status_code == 201, response.text
        assert response.json()["data"]["next_run_at"] == slot.isoformat()

    # Bad input is rejected up front with a clear, structured error.
    rejected = post(client, "/tasks", {"user": "alice", "time": hhmm, "action": "compress"})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "UNKNOWN_ACTION"
    missing = post(client, "/tasks", {"user": "carol", "time": hhmm, "action": "sync"})
    assert missing.status_code == 404

    # Nothing has run yet: the slot is still in the future.
    assert client.get("/api/v1/executions").json()["meta"]["total"] == 0

    # Act: let the background loop reach the slot on the real clock.
    executions = wait_for_executions(client, expected=4)
    time.sleep(3)  # a few more ticks, to prove nothing runs twice

    # Assert: quota decided the outcome, and each task ran exactly once.
    after = client.get("/api/v1/executions", params={"limit": 100}).json()
    assert after["meta"]["total"] == 4
    by_user = Counter((e["user"], e["status"]) for e in executions)
    assert by_user == {
        ("alice", "SUCCESS"): 2,
        ("alice", "QUOTA_EXCEEDED"): 1,
        ("bob", "SUCCESS"): 1,
    }
    assert all(datetime.fromisoformat(e["scheduled_for"]) == slot for e in executions)
    assert len({e["tick_id"] for e in executions}) == 1

    alice = client.get("/api/v1/users/alice").json()["data"]
    assert alice["usage_today"]["used"] == 2
    assert alice["usage_today"]["limit"] == 2

    tasks = client.get("/api/v1/tasks", params={"limit": 100}).json()["data"]
    assert {t["next_run_at"] for t in tasks} == {(slot + timedelta(days=1)).isoformat()}

    # A manual tick right after finds nothing due.
    manual = client.post("/api/v1/scheduler/tick").json()["data"]
    assert manual["results"] == []

    # Logs carry tick/task/user context and the simulated actions, with no secrets.
    log = log_path.read_text(encoding="utf-8", errors="replace")
    assert "[SIMULATED] backup /srv/y -> /bk" in log
    assert "Quota exceeded (2/2 today), task skipped" in log
    assert "Tick finished: 4 due, 3 success, 0 failed, 1 quota exceeded" in log
    assert "user=alice]" in log
    assert "***@localhost" in log
    assert "postgrespw123" not in log
    assert "redispw123" not in log
