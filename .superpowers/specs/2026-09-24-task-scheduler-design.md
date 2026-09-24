# Task Scheduler Service: Design Spec

- Date: 2026-09-24
- Status: Approved in brainstorming, awaiting spec review
- Business flow for readers: see [README.md](../../README.md)

## 1. Goal

Refactor the legacy single-file scheduler (below) into a modular FastAPI service that
takes user-submitted tasks, runs each one once a day at its scheduled time, and enforces
a per-user daily quota. The assessment grades four areas: module and logic design,
maintainability, AI tool usage, and error handling with logging.

```python
users = {'alice': {'quota': 3, 'executed': 0}, 'bob': {'quota': 5, 'executed': 0}}
tasks = [
    {'user': 'alice', 'time': '12:00', 'action': 'sync', 'target': '/data/x'},
    {'user': 'bob', 'time': '12:00', 'action': 'backup', 'target': '/srv/y'},
    {'user': 'alice', 'time': '12:00', 'action': 'delete', 'target': '/tmp/z'},
]
```

### Defects in the legacy code this design fixes

| Defect | Fix |
|---|---|
| `executed` never resets, so a user is locked out after day one | Daily counters in Redis keyed by date |
| Exact `HH:MM` match skips late checks and double-runs within one minute | `next_run_at` plus an atomic claim that moves it forward |
| `users[user]` raises `KeyError` and kills the loop | Domain errors; one task's failure never stops others |
| `print` instead of logging | `logging` with `tick_id`, `task_id`, `user` context |
| Action dispatch by string inside the loop | Strategy classes in a registry |
| Global mutable state | Postgres + Redis behind repository interfaces |

## 2. Scope

### In scope

- User management with a daily quota.
- Task model with dictionary input and per-action parameter validation.
- Extensible async executor using the Strategy pattern (`sync`, `backup`, `delete`, all
  simulated).
- Tick-based scheduler with a background loop and a manual trigger endpoint.
- Logging with request-independent correlation IDs.
- Thin FastAPI layer over the domain services.
- Optional extensions from the brief: action strategies (OOP) and async execution. Both
  are in.

### Out of scope

- Authentication, authorization, and rate limiting. The brief doesn't ask for them, and
  adding them would hide the parts being graded.
- Updating or deleting tasks and users through the API.
- Real filesystem side effects. Every action only logs.
- Retrying failed executions.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Quota is per calendar day and resets by itself | The brief says tasks run daily; a lifetime quota locks users out |
| D2 | Due when `next_run_at <= now`; a late check still runs the task once | A late scheduler shouldn't drop work, and a long outage shouldn't replay days |
| D3 | A new task's first run is the first occurrence of its time after submission | A 12:00 task submitted at 15:00 running instantly would surprise users |
| D4 | Quota is consumed on attempt, not on success | Failed runs still use resources; closes unlimited retries |
| D5 | User, action, and params are checked before quota is consumed | Configuration mistakes shouldn't cost quota |
| D6 | Claimed tasks move `next_run_at` whatever the outcome | A quota-rejected task isn't retried the same day |
| D7 | Redis unreachable means the task doesn't run (fail closed) | Running without a quota check breaks the core guarantee |
| D8 | Claim uses `SELECT ... FOR UPDATE SKIP LOCKED` in Postgres | Safe across concurrent ticks and multiple app instances, unlike an in-process lock |
| D9 | Quota check-and-increment is one Redis Lua script | Atomic across processes without a separate lock |
| D10 | Executors don't touch the database; the scheduler preloads users and bulk-saves results | `AsyncSession` isn't safe for concurrent use inside `asyncio.gather` |
| D11 | Days follow one configured time zone, default `Asia/Jakarta` | "Today" must be unambiguous for both quota and scheduling |
| D12 | Tick-based scheduler written in-house, no APScheduler | The scheduling logic is what's graded, and it must be testable with a fake clock |

Accepted trade-off: if Redis restarts mid-day, that day's counters are lost and users
may exceed quota until midnight. `executions` in Postgres keeps the full history.

## 4. Architecture

```text
app/
├── main.py                        # create_app(), lifespan, exception handlers
├── core/
│   ├── config.py                  # Settings (pydantic-settings, reads .env)
│   ├── logging.py                 # configure_logging(), ContextFilter, context vars
│   └── clock.py                   # Clock protocol, SystemClock
├── domain/
│   ├── models.py                  # User, Task, ExecutionResult, ExecutionStatus, QuotaDecision
│   ├── errors.py                  # DomainError hierarchy
│   └── scheduling.py              # compute_next_run()
├── strategies/
│   ├── base.py                    # ActionStrategy ABC, TargetParams
│   ├── registry.py                # StrategyRegistry, build_default_registry()
│   ├── sync.py
│   ├── backup.py
│   └── delete.py
├── db/
│   ├── base.py                    # DeclarativeBase
│   └── session.py                 # create_engine(), create_session_factory()
├── models/
│   ├── user.py                    # UserRecord
│   ├── task.py                    # TaskRecord
│   └── execution.py               # ExecutionRecord
├── repositories/
│   ├── interfaces.py              # UserRepository, TaskRepository, ExecutionRepository, QuotaStore (Protocols)
│   ├── user_repository.py         # SqlUserRepository
│   ├── task_repository.py         # SqlTaskRepository (includes claim_due)
│   ├── execution_repository.py    # SqlExecutionRepository
│   └── quota_store.py             # RedisQuotaStore
├── services/
│   ├── user_service.py
│   ├── task_service.py
│   ├── task_executor.py
│   ├── scheduler.py               # Scheduler, SchedulerRunner, TickReport
│   └── seed.py                    # Idempotent legacy demo data
├── schemas/
│   ├── common.py                  # ApiResponse[T], ErrorBody, PageMeta
│   ├── user.py
│   ├── task.py
│   ├── action.py
│   └── execution.py
└── api/
    ├── container.py               # AppContainer: builds and owns all services
    ├── deps.py                    # Depends() providers reading app.state.container
    ├── health.py                  # GET /health
    └── v1/
        ├── router.py
        └── routes/
            ├── users.py
            ├── actions.py
            ├── tasks.py
            ├── scheduler.py
            └── executions.py
alembic/                           # env.py + versions/0001_initial.py
scripts/create_databases.py        # Creates task_scheduler and task_scheduler_test if missing
```

Import direction: `api` → `services` → (`domain`, `strategies`, `repositories`).
`repositories` may import `domain` and `models`. `domain` imports nothing from `app`.
Services only see domain dataclasses; ORM records never leave `repositories/`.

## 5. Domain Model

All domain models are frozen dataclasses. Datetimes are timezone-aware.

```python
class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

@dataclass(frozen=True)
class User:
    username: str
    daily_quota: int
    created_at: datetime

@dataclass(frozen=True)
class Task:
    id: UUID
    username: str
    run_at: time              # wall-clock time in the configured zone, seconds = 0
    action: str
    params: Mapping[str, Any]
    next_run_at: datetime
    created_at: datetime

@dataclass(frozen=True)
class ClaimedTask:
    task: Task
    scheduled_for: datetime   # next_run_at before the claim moved it

@dataclass(frozen=True)
class ExecutionResult:
    id: UUID
    task_id: UUID
    username: str
    action: str
    status: ExecutionStatus
    message: str
    tick_id: str
    scheduled_for: datetime
    started_at: datetime
    duration_ms: int

@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    used: int                 # count after this call
    limit: int
```

### `compute_next_run(run_at: time, tz: ZoneInfo, after: datetime) -> datetime`

Returns the first moment strictly after `after` whose wall-clock time in `tz` equals
`run_at`:

1. `local = after.astimezone(tz)`
2. `candidate = datetime.combine(local.date(), run_at, tzinfo=tz)`
3. If `candidate <= after`, use `datetime.combine(local.date() + timedelta(days=1), run_at, tzinfo=tz)`.

Used at task creation (`after = created_at`) and at claim (`after = now`).

### Errors

```python
class DomainError(Exception):
    code: str                 # machine-readable, e.g. "USER_NOT_FOUND"
    http_status: int
    def __init__(self, message: str): ...
```

| Class | `code` | HTTP | Message format |
|---|---|---|---|
| `UserNotFoundError` | `USER_NOT_FOUND` | 404 | `User '{username}' not found` |
| `UserAlreadyExistsError` | `USER_ALREADY_EXISTS` | 409 | `User '{username}' already exists` |
| `UnknownActionError` | `UNKNOWN_ACTION` | 422 | `Unknown action '{action}'. Available: {sorted names}` |
| `InvalidTaskParamsError` | `INVALID_TASK_PARAMS` | 422 | `Invalid params for action '{action}': {field}: {reason}; ...` |

`http_status` on a domain error is a pragmatic shortcut so one handler can map all of
them; the domain layer still never imports FastAPI.

## 6. Strategies

```python
class ActionStrategy(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]

    def __init__(self, simulated_latency: float = 0.1) -> None: ...

    def parse_params(self, raw: Mapping[str, Any]) -> BaseModel:
        """Validate raw params. Raises InvalidTaskParamsError."""

    @abstractmethod
    async def execute(self, params: BaseModel) -> str:
        """Run the simulated action and return a human-readable result message."""
```

`TargetParams` (Pydantic, `extra="forbid"`): `target: str`, non-empty, must start with
`/`. `BackupParams` extends it with `destination: str | None = None` (same rule when
set). Unknown keys are rejected.

| Action | Params | Log line (INFO, logger `app.strategies`) |
|---|---|---|
| `sync` | `target` | `[SIMULATED] sync {target}` |
| `backup` | `target`, `destination?` | `[SIMULATED] backup {target} -> {destination or '<default>'}` |
| `delete` | `target` | `[SIMULATED] delete {target}` |

Each `execute` awaits `asyncio.sleep(self.simulated_latency)` so concurrent execution is
observable. Tests construct strategies with `simulated_latency=0`.

`StrategyRegistry`: `register(strategy)` raises `ValueError` on duplicate names;
`get(name)` raises `UnknownActionError`; `list()` returns strategies sorted by name.
`build_default_registry(simulated_latency)` registers the three actions.

## 7. Storage

### Postgres tables (migration `0001_initial`)

**users**

| Column | Type | Constraints |
|---|---|---|
| `username` | `VARCHAR(50)` | PK |
| `daily_quota` | `INTEGER` | NOT NULL, `CHECK (daily_quota >= 0)` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL |

**tasks**

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `username` | `VARCHAR(50)` | NOT NULL, FK → `users.username` |
| `run_at` | `TIME` | NOT NULL |
| `action` | `VARCHAR(50)` | NOT NULL |
| `params` | `JSONB` | NOT NULL, default `{}` |
| `next_run_at` | `TIMESTAMPTZ` | NOT NULL, indexed |
| `created_at` | `TIMESTAMPTZ` | NOT NULL |

Also indexed on `username`.

**executions**

| Column | Type | Constraints |
|---|---|---|
| `id` | `UUID` | PK |
| `task_id` | `UUID` | NOT NULL, FK → `tasks.id` |
| `username` | `VARCHAR(50)` | NOT NULL |
| `action` | `VARCHAR(50)` | NOT NULL |
| `status` | `VARCHAR(20)` | NOT NULL, `CHECK` in the three statuses |
| `message` | `TEXT` | NOT NULL |
| `tick_id` | `VARCHAR(16)` | NOT NULL |
| `scheduled_for` | `TIMESTAMPTZ` | NOT NULL |
| `started_at` | `TIMESTAMPTZ` | NOT NULL |
| `duration_ms` | `INTEGER` | NOT NULL |

Indexed on `(username, started_at DESC)` and `status`.

### Repository interfaces

```python
class UserRepository(Protocol):
    async def add(self, user: User) -> None             # raises UserAlreadyExistsError
    async def get(self, username: str) -> User | None
    async def get_many(self, usernames: Collection[str]) -> dict[str, User]

class TaskRepository(Protocol):
    async def add(self, task: Task) -> None
    async def list(self, username: str | None, offset: int, limit: int) -> tuple[list[Task], int]
    async def claim_due(self, now: datetime, tz: ZoneInfo, limit: int) -> list[ClaimedTask]

class ExecutionRepository(Protocol):
    async def add_many(self, results: Sequence[ExecutionResult]) -> None
    async def list(self, username: str | None, status: ExecutionStatus | None,
                   offset: int, limit: int) -> tuple[list[ExecutionResult], int]

class QuotaStore(Protocol):
    async def try_consume(self, username: str, day: date, limit: int) -> QuotaDecision
    async def get_usage(self, username: str, day: date) -> int
    async def ping(self) -> None
```

SQL repositories take an `async_sessionmaker` and open one session per method call.
`add` in `SqlUserRepository` maps `IntegrityError` on the primary key to
`UserAlreadyExistsError`.

`claim_due`, in one transaction:

```sql
SELECT * FROM tasks
WHERE next_run_at <= :now
ORDER BY next_run_at
LIMIT :limit
FOR UPDATE SKIP LOCKED
```

For each row, set `next_run_at = compute_next_run(row.run_at, tz, now)`, then commit and
return `ClaimedTask(task, scheduled_for=<old next_run_at>)`.

### Redis quota store

- Key: `task_scheduler:quota:{username}:{YYYY-MM-DD}`, TTL 172800 seconds.
- `try_consume` runs this script (registered once with `register_script`):

```lua
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
  return {0, current}
end
current = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {1, current}
```

- `get_usage` returns `int(GET key or 0)`.
- Redis connection errors (`redis.exceptions.RedisError`) propagate to the executor,
  which turns them into a `FAILED` result.

## 8. Services

### `UserService`

- `register(username, daily_quota) -> User`
- `get(username) -> User` (raises `UserNotFoundError`)
- `get_usage_today(username) -> tuple[User, int]`

### `TaskService`

`submit(raw: Mapping[str, Any]) -> Task` accepts the dictionary shape
`{"user", "time", "action", "params"}`. The API schema already validates types; the
service checks meaning:

1. User exists, else `UserNotFoundError`.
2. `registry.get(action)`, else `UnknownActionError`.
3. `strategy.parse_params(params)`, else `InvalidTaskParamsError`.
4. `now = clock.now()`; `next_run_at = compute_next_run(run_at, tz, now)`.
5. Save a `Task` with a new `uuid4` and store `params` as the validated model dumped back
   to a dict.

`list(username, page, limit) -> tuple[list[Task], int]`.

### `TaskExecutor`

`execute(claimed: ClaimedTask, user: User | None, now: datetime, tick_id: str) -> ExecutionResult`

Sets context vars `task_id` and `user`, records `started_at`, then:

1. `user is None` → `FAILED`, `User '{username}' not found`. No quota used.
2. `registry.get(action)` fails → `FAILED` with the `UnknownActionError` message.
3. `parse_params` fails → `FAILED` with the `InvalidTaskParamsError` message.
4. `quota.try_consume(username, now.date(), user.daily_quota)`:
   - `RedisError` → `FAILED`, `Quota service unavailable`; logged at ERROR with traceback.
   - Not allowed → `QUOTA_EXCEEDED`, `Quota exceeded ({used}/{limit} today)`; logged at WARNING.
5. `await asyncio.wait_for(strategy.execute(params), timeout=settings.task_timeout_seconds)`:
   - Returns → `SUCCESS` with the strategy's message; INFO.
   - `TimeoutError` → `FAILED`, `{action} timed out after {n}s`; ERROR.
   - Any other `Exception` → `FAILED`, `{action} failed: {exc}`; ERROR with traceback.

The executor never raises. It has no database access (D10).

### `Scheduler`

`tick() -> TickReport(tick_id: str, started_at: datetime, results: list[ExecutionResult])`

1. `tick_id = uuid4().hex[:8]`; set context var; `now = clock.now()`.
2. `claimed = await tasks.claim_due(now, tz, settings.claim_batch_size)`.
3. None claimed → DEBUG `No tasks due`, return an empty report.
4. INFO `{n} tasks due`.
5. `users = await users.get_many({c.task.username for c in claimed})`.
6. `results = await asyncio.gather(*(executor.execute(c, users.get(c.task.username), now, tick_id) for c in claimed))`.
7. `await executions.add_many(results)`.
8. INFO `Tick finished: {n} due, {s} success, {f} failed, {q} quota exceeded`.

### `SchedulerRunner`

- `start()` creates the loop task; `stop()` cancels it and awaits its exit.
- Loop: `await scheduler.tick()`; any `Exception` is logged with traceback and the loop
  continues; then `await asyncio.sleep(settings.tick_interval_seconds)`.
- Started in the FastAPI lifespan only when `SCHEDULER_ENABLED=true`.

### `seed_demo_data`

When `SEED_DEMO_DATA=true`, at startup: register `alice` (quota 3) and `bob` (quota 5)
if missing, and submit the three legacy tasks for any user that was just created. Safe to
run on every startup.

## 9. API

All `/api/v1` responses use one envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": null
}
```

On error, `success` is `false`, `data` is `null`, and `error` is
`{"code": "...", "message": "...", "error_id": "..." | null}`. List endpoints fill `meta`
with `{"total": int, "page": int, "limit": int}`. `page` is 1-based; `limit` is 1–100,
default 20.

| Method | Path | Body / query | Success |
|---|---|---|---|
| POST | `/api/v1/users` | `{"username": str, "daily_quota": int}` | 201, user |
| GET | `/api/v1/users/{username}` | – | 200, user plus `usage_today: {"date", "used", "limit"}` |
| GET | `/api/v1/actions` | – | 200, `[{"name", "description", "params_schema"}]` |
| POST | `/api/v1/tasks` | `{"user", "time": "HH:MM", "action", "params": {}}` | 201, task |
| GET | `/api/v1/tasks` | `user?`, `page`, `limit` | 200, tasks + meta |
| POST | `/api/v1/scheduler/tick` | – | 200, `{"tick_id", "started_at", "results": [...]}` |
| GET | `/api/v1/executions` | `user?`, `status?`, `page`, `limit` | 200, executions + meta |
| GET | `/health` | – | 200 or 503, `{"status", "components": {"postgres", "redis"}}` |

Request validation:
- `username` matches `^[a-z0-9_]{3,50}$`.
- `daily_quota` is between 0 and 10000.
- `time` matches `^([01]\d|2[0-3]):[0-5]\d$`.
- `action` is 1–50 characters.
- `params` is an object.

Exception handlers in `main.py`:
- `DomainError` → its `http_status`, `code`, and message.
- `RequestValidationError` → 422, `VALIDATION_ERROR`, fields and reasons joined into
  the message.
- Any other `Exception` → 500, `INTERNAL_ERROR`, `An unexpected error occurred`, with a
  new `error_id`. The same `error_id` is logged at ERROR with the traceback.

`AppContainer` is built in the lifespan from `Settings`: engine, session factory, Redis
client, repositories, registry, services, scheduler, and runner. It's stored on
`app.state.container`. `deps.py` providers read from it, and tests replace them with
`app.dependency_overrides` or a container built around a `FakeClock`. On shutdown,
`stop()` runs on the runner, then the Redis client closes and the engine is disposed.

## 10. Logging

- `configure_logging(level)` runs once in `create_app`.
- Format: `%(asctime)s %(levelname)-7s %(name)-14s [tick=%(tick_id)s task=%(task_id)s user=%(user)s] %(message)s`.
- `ContextFilter` fills `tick_id`, `task_id`, and `user` from `contextvars.ContextVar`s,
  defaulting to `-`.
- `asyncio.gather` wraps each coroutine in a task with a copied context, so values set
  inside one executor call don't leak into another.
- Logger names: `app.scheduler`, `app.executor`, `app.strategies`, `app.api`, `app.seed`.
- Credentials never appear in logs. Settings are logged at startup with URLs masked.

## 11. Configuration

`Settings` (pydantic-settings, `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | required | `postgresql+asyncpg://...@localhost:5432/task_scheduler` |
| `TEST_DATABASE_URL` | required for tests | Same server, database `task_scheduler_test` |
| `REDIS_URL` | required | `redis://:...@localhost:6379/1` |
| `TEST_REDIS_URL` | required for tests | Same server, db index 2 |
| `TIMEZONE` | `Asia/Jakarta` | Defines "today" |
| `SCHEDULER_ENABLED` | `true` | Starts the background loop |
| `TICK_INTERVAL_SECONDS` | `30` | Loop interval, 1–3600 |
| `TASK_TIMEOUT_SECONDS` | `30` | Per-task timeout, 1–600 |
| `CLAIM_BATCH_SIZE` | `100` | Max tasks claimed per tick, 1–1000 |
| `SIMULATED_LATENCY_SECONDS` | `0.1` | Strategy sleep, 0–10 |
| `SEED_DEMO_DATA` | `false` | Loads the legacy users and tasks |
| `LOG_LEVEL` | `INFO` | Root log level |

`.env` holds real credentials and is gitignored. `.env.example` has the same keys with
placeholder values.

`scripts/create_databases.py` connects to the `postgres` maintenance database and runs
`CREATE DATABASE` for `task_scheduler` and `task_scheduler_test` only if they don't
exist. It touches no other database.

## 12. Dependencies

Runtime: `fastapi[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]>=2`, `asyncpg`,
`alembic`, `redis>=5`.

Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `ruff`, `mypy`.

Python 3.12, local `.venv`, declared in `pyproject.toml` with a `dev` extra.

## 13. Testing

All tests are written before the code they cover.

### Unit (`tests/unit`, no Postgres, Redis, or HTTP)

In-memory fakes live in `tests/fakes.py`: `FakeClock`, `InMemoryUserRepository`,
`InMemoryTaskRepository`, `InMemoryExecutionRepository`, `InMemoryQuotaStore`, and a
`FailingQuotaStore`.

- `compute_next_run`:
  - same day, later
  - same day, earlier → tomorrow
  - exactly equal → tomorrow
  - `after` given in UTC but compared in `Asia/Jakarta`
- Strategies and registry:
  - param validation (missing `target`, relative path, unknown key)
  - duplicate registration
  - unknown action message lists available names
- `TaskService`:
  - valid submit sets `next_run_at` per D3
  - each error type
- `TaskExecutor`:
  - success
  - missing user (quota untouched)
  - bad params (quota untouched)
  - quota exceeded
  - quota store raises (strategy not called)
  - strategy raises (quota consumed)
  - timeout
- `Scheduler`:
  - late tick catches up
  - second tick the same day claims nothing
  - after midnight the task is due again
  - four alice tasks with quota 3 → exactly 3 `SUCCESS` and 1 `QUOTA_EXCEEDED`
  - one failing strategy doesn't affect the others
  - results are saved

### Integration (`tests/integration`, real Postgres and Redis)

- Session fixture:
  - creates `task_scheduler_test` if missing
  - runs `metadata.create_all`
  - truncates the three tables before each test
- Redis fixture:
  - connects to `TEST_REDIS_URL`
  - deletes only keys matching `task_scheduler:*` via `SCAN`
- `RedisQuotaStore`:
  - 10 concurrent `try_consume` calls with limit 3 → exactly 3 allowed
  - keys carry a TTL
  - a different date starts at 0
- `SqlTaskRepository.claim_due`:
  - two concurrent calls return disjoint task sets
  - `next_run_at` moves to the next occurrence
- API via `httpx.AsyncClient(transport=ASGITransport(app))` with `FakeClock` and
  `SCHEDULER_ENABLED=false`:
  - register → submit → tick → list executions
  - 404, 409, and 422 envelopes
  - pagination `meta`
  - `/health`
- Legacy parity: seed the legacy data with the clock at 08:00, advance it to 12:00 the
  same day, tick. The results must match the legacy script's output: alice `sync /data/x`,
  bob `backup /srv/y`, alice `delete /tmp/z`, all `SUCCESS`.
- Migration: `alembic upgrade head` on an empty schema produces the same tables as the
  metadata.

### Gates

- `ruff check` and `ruff format --check` clean.
- `mypy app` clean in strict mode.
- Coverage of `app/` at 80% or higher.
