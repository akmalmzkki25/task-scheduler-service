# Task Scheduler Service Implementation Plan

> **For agentic workers:** Executed inline with superpowers:executing-plans (user's
> choice, no subagents). Steps use checkbox (`- [ ]`) syntax for tracking. Each task
> follows TDD: write the listed tests, watch them fail, implement, watch them pass,
> commit.

**Goal:** Refactor the legacy scheduler script into a modular FastAPI service with daily
per-user quotas, strategy-based async actions, and traceable logging.

**Architecture:** Pure domain layer (dataclasses, errors, `compute_next_run`), strategy
registry, services that depend on repository Protocols, Postgres (SQLAlchemy async)
and Redis (Lua quota script) implementations, and a thin FastAPI layer wired through an
`AppContainer`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 async
+ asyncpg, Alembic, redis-py asyncio, pytest + pytest-asyncio, httpx, ruff, mypy.

**Spec:** [.superpowers/specs/2026-09-24-task-scheduler-design.md](../specs/2026-09-24-task-scheduler-design.md)

## Global Constraints

- Python 3.12, `.venv` in the project root, dependencies in `pyproject.toml`.
- Default time zone `Asia/Jakarta`; every datetime is timezone-aware.
- Postgres databases `task_scheduler` and `task_scheduler_test` only; never touch other
  databases on the shared server.
- Redis db 1 (app) and db 2 (tests); tests delete only `task_scheduler:*` keys, never
  `FLUSHDB`/`FLUSHALL`.
- Credentials only in `.env` (gitignored); `.env.example` holds placeholders.
- Code, comments, logs, and commits in English; commits follow Conventional Commits and
  end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Actions are simulated; nothing touches the filesystem.
- All tests live in the separate root-level `tests/` folder (`tests/unit`,
  `tests/integration`, shared fakes in `tests/fakes.py`), never inside `app/`.
- Gates: `ruff check`, `ruff format --check`, `mypy app` (strict), coverage of `app/` ≥ 80%.

Commands below use Windows paths (`.venv/Scripts/...`).

---

### Task 1: Project scaffold and settings

**Files:**
- Create: `pyproject.toml`, `.env`, `.env.example`, `app/__init__.py`,
  `app/core/__init__.py`, `app/core/config.py`, `scripts/create_databases.py`,
  `tests/__init__.py`, `tests/conftest.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings` (fields from spec §11), `get_settings() -> Settings` (cached),
  `Settings.tz -> ZoneInfo`, `mask_url(url: str) -> str`.

- [ ] Create venv and install: `python -m venv .venv`, then
  `.venv/Scripts/python -m pip install -e ".[dev]"`.
- [ ] Tests: `Settings` reads values from kwargs/env; `tz` returns `ZoneInfo("Asia/Jakarta")`
  by default; `TICK_INTERVAL_SECONDS=0` raises `ValidationError`; `mask_url` hides the
  password in both Postgres and Redis URLs.
- [ ] Implement `config.py`; run `pytest tests/unit/test_config.py -v` → PASS.
- [ ] Run `scripts/create_databases.py`; confirm both databases exist with
  `docker exec postgres psql -U postgres -c "\l task_scheduler*"`.
- [ ] Commit `chore: scaffold project, settings, and database bootstrap`.

### Task 2: Domain models, errors, and next-run calculation

**Files:**
- Create: `app/domain/__init__.py`, `app/domain/models.py`, `app/domain/errors.py`,
  `app/domain/scheduling.py`, `tests/unit/test_scheduling.py`, `tests/unit/test_errors.py`

**Interfaces:**
- Produces: `User`, `Task`, `ClaimedTask`, `ExecutionResult`, `ExecutionStatus`,
  `QuotaDecision` (spec §5); `DomainError(message)` with `code`, `http_status`,
  `message`; `UserNotFoundError(username)`, `UserAlreadyExistsError(username)`,
  `UnknownActionError(action, available: Iterable[str])`, `InvalidTaskParamsError(action, details: str)`;
  `compute_next_run(run_at: time, tz: ZoneInfo, after: datetime) -> datetime`.

- [ ] Tests for `compute_next_run`: later today → today; earlier today → tomorrow; exactly
  equal → tomorrow; `after` in UTC (`05:30Z` = `12:30` Jakarta) with `run_at=12:00` →
  tomorrow 12:00 Jakarta; result is aware and in `tz`.
- [ ] Tests for errors: each message format and `code`/`http_status` from spec §5;
  `UnknownActionError` lists available names sorted.
- [ ] Implement; run `pytest tests/unit -v` → PASS.
- [ ] Commit `feat: add domain models, errors, and next-run calculation`.

### Task 3: Clock and contextual logging

**Files:**
- Create: `app/core/clock.py`, `app/core/logging.py`, `tests/fakes.py` (start with
  `FakeClock`), `tests/unit/test_logging.py`

**Interfaces:**
- Produces: `Clock` Protocol (`now() -> datetime`), `SystemClock(tz)`;
  `tick_id_var`, `task_id_var`, `user_var` (`ContextVar[str]`, default `"-"`);
  `ContextFilter`; `configure_logging(level: str) -> None`; `LOG_FORMAT`.
  `FakeClock(start: datetime)` with `now()`, `set(dt)`, `advance(**timedelta_kwargs)`.

- [ ] Tests: a record passing through `ContextFilter` gets `-` defaults; values set in a
  context var appear on the record; two coroutines under `asyncio.gather` that set
  different `task_id` values each log their own value; `SystemClock.now()` is aware and
  in its zone.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add clock abstraction and context-aware logging`.

### Task 4: Action strategies and registry

**Files:**
- Create: `app/strategies/__init__.py`, `base.py`, `registry.py`, `sync.py`, `backup.py`,
  `delete.py`, `tests/unit/test_strategies.py`

**Interfaces:**
- Produces: `ActionStrategy` (spec §6: `name`, `description`, `params_model`,
  `__init__(simulated_latency=0.1)`, `parse_params(raw) -> BaseModel`,
  `async execute(params) -> str`); `TargetParams`, `BackupParams`;
  `SyncStrategy`, `BackupStrategy`, `DeleteStrategy`; `StrategyRegistry` with
  `register`, `get`, `list`, `names`; `build_default_registry(simulated_latency: float)`.

- [ ] Tests: each strategy returns its `[SIMULATED] ...` message and logs it; missing
  `target`, relative path, empty string, and unknown key raise `InvalidTaskParamsError`
  naming the field; backup without destination uses `<default>`; registry `get` of unknown
  name raises `UnknownActionError` listing `backup, delete, sync`; duplicate `register`
  raises `ValueError`.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add action strategies and registry`.

### Task 5: Repository interfaces, fakes, UserService, TaskService

**Files:**
- Create: `app/repositories/__init__.py`, `app/repositories/interfaces.py`,
  `app/services/__init__.py`, `app/services/user_service.py`,
  `app/services/task_service.py`, extend `tests/fakes.py`,
  `tests/unit/test_user_service.py`, `tests/unit/test_task_service.py`

**Interfaces:**
- Produces: Protocols from spec §7. `UserService(users, quota, clock)` with
  `register(username, daily_quota) -> User`, `get(username) -> User`,
  `get_usage_today(username) -> tuple[User, int, date]`.
  `TaskService(users, tasks, registry, clock, tz)` with `submit(raw: Mapping) -> Task`,
  `list(username, page, limit) -> tuple[list[Task], int]`.
  Fakes: `InMemoryUserRepository`, `InMemoryTaskRepository` (with `claim_due` using
  `compute_next_run`), `InMemoryExecutionRepository`, `InMemoryQuotaStore`,
  `FailingQuotaStore`.

- [ ] Tests: register then get; duplicate raises `UserAlreadyExistsError`; unknown get
  raises `UserNotFoundError`; usage today reads the quota store. Submit valid task at
  08:00 for 12:00 → `next_run_at` today 12:00; at 15:00 → tomorrow 12:00; unknown user,
  unknown action, bad params each raise their error; stored params are the validated
  dump; list paginates and filters by user.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add user and task services`.

### Task 6: TaskExecutor

**Files:**
- Create: `app/services/task_executor.py`, `tests/unit/test_task_executor.py`

**Interfaces:**
- Consumes: registry, `QuotaStore`, `Clock`, domain models.
- Produces: `TaskExecutor(registry, quota, clock, timeout_seconds: float)` with
  `async execute(claimed: ClaimedTask, user: User | None, now: datetime, tick_id: str) -> ExecutionResult`
  following spec §8 step order.

- [ ] Tests: success → `SUCCESS`, quota 1 used; `user=None` → `FAILED`, quota 0 used;
  unknown action → `FAILED`, quota 0; bad params → `FAILED`, quota 0; quota full →
  `QUOTA_EXCEEDED` with `Quota exceeded (3/3 today)`; `FailingQuotaStore` →
  `FAILED` `Quota service unavailable` and strategy not called; strategy raising →
  `FAILED`, quota consumed; slow strategy with timeout 0.01 → `FAILED` `... timed out
  after 0.01s`; executor never raises; `duration_ms >= 0`; WARNING/ERROR records emitted.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add task executor with quota and timeout handling`.

### Task 7: Scheduler and SchedulerRunner

**Files:**
- Create: `app/services/scheduler.py`, `tests/unit/test_scheduler.py`

**Interfaces:**
- Produces: `TickReport(tick_id, started_at, results)`;
  `Scheduler(tasks, users, executions, executor, clock, tz, claim_batch_size)` with
  `async tick() -> TickReport`; `SchedulerRunner(scheduler, interval_seconds)` with
  `start()`, `async stop()`, `is_running`.

- [ ] Tests: task due at 12:00 ticked at 12:03 runs; second tick same day claims
  nothing; after `advance(days=1)` due again; four alice tasks (quota 3) → 3 `SUCCESS`
  + 1 `QUOTA_EXCEEDED`; a failing strategy doesn't affect a sibling; results saved to the
  execution repo with the tick's `tick_id`; empty tick returns empty results;
  runner calls tick repeatedly, survives a tick that raises, and stops cleanly.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add tick-based scheduler and background runner`.

### Task 8: Postgres persistence and migration

**Files:**
- Create: `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`,
  `app/models/__init__.py`, `app/models/user.py`, `app/models/task.py`,
  `app/models/execution.py`, `app/repositories/user_repository.py`,
  `app/repositories/task_repository.py`, `app/repositories/execution_repository.py`,
  `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`,
  `alembic/versions/0001_initial.py`, `tests/integration/__init__.py`,
  `tests/integration/conftest.py`, `tests/integration/test_sql_repositories.py`

**Interfaces:**
- Produces: `Base`; `create_engine(url) -> AsyncEngine`;
  `create_session_factory(engine) -> async_sessionmaker[AsyncSession]`;
  `UserRecord`, `TaskRecord`, `ExecutionRecord`; `SqlUserRepository`,
  `SqlTaskRepository`, `SqlExecutionRepository` (constructor takes the session factory).
  Integration fixtures: `engine`, `session_factory` (tables truncated per test).

- [ ] Tests: add/get/get_many users; duplicate add raises `UserAlreadyExistsError`; task
  add/list with pagination and total; `claim_due` returns only due tasks and moves
  `next_run_at` to the next occurrence; two concurrent `claim_due` calls on separate
  sessions return disjoint sets covering all due tasks; executions `add_many` and
  `list` filtered by user and status, newest first; `alembic upgrade head` on a fresh
  schema creates the three tables.
- [ ] Implement; run `pytest tests/integration/test_sql_repositories.py -v` → PASS.
- [ ] Run `.venv/Scripts/alembic upgrade head` against `task_scheduler`.
- [ ] Commit `feat: add Postgres persistence and initial migration`.

### Task 9: Redis quota store

**Files:**
- Create: `app/repositories/quota_store.py`, `tests/integration/test_quota_store.py`
  (fixture `redis_client` in `tests/integration/conftest.py`)

**Interfaces:**
- Produces: `RedisQuotaStore(client: redis.asyncio.Redis, ttl_seconds: int = 172800)` with
  `try_consume`, `get_usage`, `ping`; `quota_key(username, day) -> str`.

- [ ] Tests: first consume allowed with `used=1`; limit 0 never allowed; 10 concurrent
  consumes with limit 3 → exactly 3 allowed and stored count 3; key TTL between 0 and
  172800; another date starts at 0; `get_usage` of a missing key is 0.
- [ ] Implement; run tests → PASS.
- [ ] Commit `feat: add Redis-backed atomic quota store`.

### Task 10: API layer, container, seed, health

**Files:**
- Create: `app/schemas/__init__.py`, `common.py`, `user.py`, `task.py`, `action.py`,
  `execution.py`; `app/api/__init__.py`, `container.py`, `deps.py`, `health.py`,
  `app/api/v1/__init__.py`, `router.py`, `routes/__init__.py`, `routes/users.py`,
  `routes/actions.py`, `routes/tasks.py`, `routes/scheduler.py`, `routes/executions.py`;
  `app/services/seed.py`; `app/main.py`; `tests/integration/test_api.py`,
  `tests/integration/test_legacy_parity.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI`;
  `AppContainer.build(settings, clock) -> AppContainer` and `async aclose()`;
  `seed_demo_data(user_service, task_service) -> None`; endpoints from spec §9.

- [ ] Tests: register user → 201 envelope; duplicate → 409 `USER_ALREADY_EXISTS`;
  unknown user GET → 404; invalid body → 422 `VALIDATION_ERROR`; bad params → 422
  `INVALID_TASK_PARAMS`; `/actions` lists three with `params_schema`; submit → tick →
  `/executions` shows result; `/users/alice` shows `usage_today`; list pagination `meta`;
  `/health` 200 with both components `ok`; unexpected error → 500 with `error_id`.
  Legacy parity: seed at 08:00, tick at 12:00 → alice sync `/data/x`, bob backup
  `/srv/y`, alice delete `/tmp/z`, all `SUCCESS`; seeding twice doesn't duplicate.
- [ ] Implement; run tests → PASS.
- [ ] Smoke run: `.venv/Scripts/fastapi dev app/main.py` with `SEED_DEMO_DATA=true`, hit
  `/health` and `POST /api/v1/scheduler/tick`.
- [ ] Commit `feat: add FastAPI layer, demo seed, and health check`.

### Task 11: Quality gates and docs

**Files:**
- Modify: `README.md` (add Setup, Running, API, Testing sections), any file flagged by
  ruff or mypy.

- [ ] Run `ruff check . --fix`, `ruff format .`, `mypy app`, and
  `pytest --cov=app --cov-report=term-missing`; fix until all clean and coverage ≥ 80%.
- [ ] Update README with setup, run, endpoints, and test commands that were actually run.
- [ ] Commit `docs: add setup, API, and testing guide`.

## Spec Coverage Check

| Spec section | Task |
|---|---|
| §5 domain model, errors, `compute_next_run` | 2 |
| §6 strategies | 4 |
| §7 Postgres tables, repositories, claim | 8 |
| §7 Redis quota store | 9 |
| §8 UserService, TaskService | 5 |
| §8 TaskExecutor | 6 |
| §8 Scheduler, SchedulerRunner | 7 |
| §8 seed | 10 |
| §9 API, envelope, handlers, container | 10 |
| §10 logging | 3 |
| §11 configuration, create_databases | 1 |
| §12 dependencies | 1 |
| §13 gates | 11 |
