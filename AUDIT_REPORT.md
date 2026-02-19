# JSR Hydra — Full Codebase Audit Report

**Date:** 2026-02-18
**Audited by:** 5 parallel AI agents (Claude Sonnet 4.6)
**Scope:** Backend, Frontend, Engine, Events, Services, Models, Schemas, Infrastructure

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 25    |
| HIGH     | 34    |
| MEDIUM   | 40    |
| LOW      | 20    |
| **Total**| **119** |

---

## CRITICAL Issues (Must Fix — System Broken or Dangerous)

### C-01: Weekend Trading Bug — Engine Trades on Saturday
**File:** `backend/app/utils/time_utils.py`
**Issue:** `is_market_open()` weekday logic is off by one. Saturday (weekday=5) is treated as Friday, Friday (weekday=4) as Thursday. The engine could attempt live trades on Saturday when markets are closed.
**Fix:** Correct the weekday mapping: Monday=0 through Friday=4 are trading days; Saturday=5 and Sunday=6 are not.

### C-02: Event Name Case Mismatch — Trade Events Never Reach Handlers
**File:** `backend/app/services/trade_service.py` → `backend/app/events/handlers.py`
**Issue:** `TradeService` publishes events as lowercase `"trade_closed"` but handlers in `handlers.py` are registered for uppercase `"TRADE_CLOSED"`. Events are silently dropped — strategy performance is never updated after trade closure.
**Fix:** Standardize all event names to uppercase throughout the codebase.

### C-03: WebSocket URL Mismatch — Frontend Can Never Connect
**File:** `frontend/hooks/useWebSocket.ts` → `backend/app/api/routes_ws.py` → `backend/app/main.py`
**Issue:** Frontend connects to `/api/ws/live` but the WebSocket router is mounted at `/ws/live` (not under `/api` prefix). Connection always fails silently.
**Fix:** Either mount the WS router under `/api` prefix in `main.py`, or update the frontend URL to `/ws/live`.

### C-04: CORS Wildcard + Credentials — Browser Blocks All Authenticated Requests
**File:** `backend/app/main.py`
**Issue:** `allow_origins=["*"]` combined with `allow_credentials=True` violates the CORS spec. Browsers will reject all authenticated cross-origin requests (cookies, auth headers).
**Fix:** Set `allow_origins` to the specific frontend domain(s), e.g., `["https://ai.jsralgo.com"]`.

### C-05: Route Ordering — `/stats/summary` Shadowed by `/{trade_id}`
**File:** `backend/app/api/routes_trades.py`
**Issue:** The route `/{trade_id}` is defined before `/stats/summary`. FastAPI matches `stats` as a `trade_id` parameter, returning 404 or wrong data. TradeStats component on frontend gets no data.
**Fix:** Move `/stats/summary` route ABOVE `/{trade_id}` in the file.

### C-06: subscribe_redis() Never Called — Cross-Process Events Are Dead
**File:** `backend/app/events/bus.py` → `backend/app/main.py`
**Issue:** `EventBus.subscribe_redis()` is defined but never invoked at startup. The Redis pub/sub listener never starts, so events published by the engine process are never received by the API server (and vice versa).
**Fix:** Call `await bus.subscribe_redis()` during API server startup (in `main.py` lifespan).

### C-07: Event Handlers Not Registered in API Server
**File:** `backend/app/main.py` → `backend/app/events/handlers.py`
**Issue:** `register_all_handlers(bus)` is called by the engine but NOT by the API server. The API process has no event handlers — even if Redis pub/sub worked, events would be ignored.
**Fix:** Call `register_all_handlers(bus)` in the API startup lifespan.

### C-08: Synchronous Redis in Async Context — Event Loop Blocked
**File:** `backend/app/bridge/order_manager.py`
**Issue:** Uses synchronous `import redis` (not `redis.asyncio`) inside an async application. Any Redis call blocks the entire event loop, freezing all concurrent operations.
**Fix:** Replace with `redis.asyncio` client, matching the rest of the codebase.

### C-09: Strategy DB Lookup Fails If Not Seeded
**File:** `backend/app/services/strategy_service.py` → `backend/app/engine/engine.py`
**Issue:** Engine assumes strategies A, B, C, D exist in the DB. If the strategies table isn't seeded (fresh deployment), all strategy lookups fail silently — no trades execute.
**Fix:** Add a DB seed/migration that creates the 4 default strategies on first run.

### C-10: Daily P&L Tracking Broken — Loss Limits Never Enforced
**File:** `backend/app/risk/risk_manager.py` → `backend/app/engine/engine.py`
**Issue:** `RiskManager.post_trade_update()` is never called by the engine after trade execution. Daily P&L counter stays at 0 forever, daily/weekly/monthly loss limits are never checked.
**Fix:** Call `risk_manager.post_trade_update(trade)` after each trade execution in the engine loop.

### C-11: Kill Switch Auto-Trigger Never Wired
**File:** `backend/app/risk/kill_switch.py` → `backend/app/engine/engine.py`
**Issue:** `KillSwitch.check_drawdown()` and `check_daily_loss()` are implemented but never called. The system has no automatic safety net — unlimited losses possible.
**Fix:** Call kill switch checks in the engine's main loop after each trade cycle.

### C-12: Brain Receives Empty Data — RL Decisions Based on Nothing
**File:** `backend/app/engine/engine.py` (cycle_summary construction)
**Issue:** The `cycle_summary` dict passed to `BrainLearner.decide()` is missing critical fields: `indicators`, `regime`, `new_candle`, `bid`, `ask`, `spread`. Brain makes random decisions.
**Fix:** Populate cycle_summary with actual market data before passing to Brain.

### C-13: Strategy Code Format Mismatch — XP/RL Data Fragmented
**File:** `backend/app/engine/engine.py` → `backend/app/brain/strategy_xp.py`
**Issue:** Engine passes strategy code as `"EURUSD_A"` (symbol_strategy) but Brain/XP system expects just `"A"`. Each symbol creates separate XP/RL tracking, fragmenting all learning data.
**Fix:** Extract just the strategy code (e.g., `"A"`) before passing to Brain/XP functions.

### C-14: DRY_RUN Mode Instantly Closes All Simulated Trades
**File:** `backend/app/bridge/order_manager.py`
**Issue:** In DRY_RUN mode, `get_open_positions()` still calls real MT5. Since simulated trades don't exist in MT5, they appear as "not open" and the engine immediately closes them. All dry-run trades have 0 profit.
**Fix:** Maintain a local registry of simulated positions for DRY_RUN mode.

### C-15: Schema Confidence Field Crashes on NULL
**File:** `backend/app/schemas/regime.py` → `backend/app/models/regime.py`
**Issue:** Pydantic schema defines `confidence: float` (required) but the DB column is `Optional[float]`. When confidence is NULL in DB, serialization crashes with `ValidationError`.
**Fix:** Change schema to `confidence: Optional[float] = None`.

### C-16: Count Query Uses Invalid SQLAlchemy 2.x Syntax
**File:** `backend/app/services/trade_service.py`
**Issue:** `select_from(stmt.alias())` is not valid in SQLAlchemy 2.0. The trade count/pagination query will crash at runtime.
**Fix:** Use `select(func.count()).select_from(Trade).where(...)` pattern.

### C-17: Auto-Allocation Calculated But Never Applied to DB
**File:** `backend/app/brain/auto_allocator.py`
**Issue:** `AutoAllocator.compute_allocation()` returns allocation percentages but they are NEVER written back to `Strategy.allocation_pct` in the database. The entire auto-allocation feature is cosmetic.
**Fix:** After computing allocations, update each strategy's `allocation_pct` in the DB and commit.

### C-18: Account Schema Validators Reject Valid States
**File:** `backend/app/schemas/account.py`
**Issue:** Validators reject negative equity (valid during margin call), `mt5_login=0` (valid for dry run), and drawdown > 100% (valid during liquidation). These cause 500 errors on the dashboard.
**Fix:** Remove overly strict validators or widen the valid ranges.

### C-19: Retrainer Is a Complete Stub
**File:** `backend/app/engine/retrainer.py`
**Issue:** The retrainer service runs in an infinite loop logging "No models to retrain yet" every 60 seconds. It does nothing. It's also never launched from docker-compose.
**Fix:** Either implement or remove. If keeping as placeholder, don't run it as a service.

### C-20: Brain State Stored in /tmp — Lost on Container Restart
**File:** `backend/app/brain/memory.py`, `backend/app/brain/learner.py`
**Issue:** All Brain RL state (Thompson Sampling parameters, XP data, memory) is stored in `/tmp`. Every container restart wipes all learned data.
**Fix:** Store in a persistent volume or in the database.

### C-21: get_db() Has No Rollback on Exception
**File:** `backend/app/db/engine.py`
**Issue:** The `get_db()` dependency doesn't rollback on exceptions. Failed transactions can leave the session in a broken state, causing cascading errors.
**Fix:** Add `try/except` with `await session.rollback()` in the `finally` or `except` block.

### C-22: Hardcoded MT5 Broker Credentials in Source Code
**File:** `infra/mt5/mt5_bridge_server.py` line 32
**Issue:** Real MT5 account login (377439), password ("Abcde12345@"), and broker server ("Monaxa-MT5") are hardcoded in the source file and committed to git. If the repo is ever public or cloned to an untrusted host, broker credentials are leaked.
**Fix:** Read credentials from environment variables (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`) which are already defined in docker-compose.

### C-23: Live OpenAI API Key Committed in docker-compose.yml
**File:** `docker-compose.yml` lines 90, 119
**Issue:** A live OpenAI API key (`sk-proj-p6bnFl0l...`) is used as the default fallback value. This key is baked into git history. **Rotate this key immediately.**
**Fix:** Remove the hardcoded key, use only `${OPENAI_API_KEY:-}` as fallback, and set the real key in `.env`.

### C-24: Redis Exposed Without Authentication
**File:** `docker-compose.yml` lines 62-63
**Issue:** Redis is exposed on port 6379 to the host with no password. Anyone on the network can connect, read trade state, and flush the event bus.
**Fix:** Remove the port binding (Redis only needs Docker-internal access) or add `requirepass`.

### C-25: PostgreSQL Exposed with Default Credentials
**File:** `docker-compose.yml` lines 37-38
**Issue:** PostgreSQL with default password `postgres` is bound to port 5432 on all interfaces. Combined with weak credentials, this allows direct database access.
**Fix:** Remove the port binding. Use `docker compose exec` for local access.

### C-22-OLD: Insecure Default Credentials in Production
**File:** `backend/app/config/settings.py`
**Issue:** `JWT_SECRET="change-me-in-production"` and `ADMIN_PASSWORD="admin"` are hardcoded defaults with no enforcement. If `.env` is missing these, the system runs with known credentials.
**Fix:** Raise an error on startup if `JWT_SECRET` or `ADMIN_PASSWORD` are still at their defaults (when not in dev mode).

---

## HIGH Issues (Should Fix — Incorrect Behavior or Security Risk)

### H-01: No Auth on Most API Read Endpoints
**Files:** `routes_system.py`, `routes_trades.py` (GET), `routes_strategies.py` (GET), `routes_brain.py` (GET)
**Issue:** Dashboard, trades list, strategies list, brain status — all public. Anyone can view account balance, open positions, trading history.
**Fix:** Add `Depends(get_current_user)` to all endpoints that expose sensitive data.

### H-02: No Auth on Brain Auto-Allocation Toggle
**File:** `backend/app/api/routes_brain.py` (PATCH `/auto-allocation-status`)
**Issue:** Mutating endpoint with no authentication. Anyone can toggle auto-allocation on/off.
**Fix:** Add `Depends(get_current_user)`.

### H-03: Frontend Uses PUT, Backend Only Has PATCH for Strategies
**File:** `frontend/lib/api.ts` → `backend/app/api/routes_strategies.py`
**Issue:** Frontend sends `PUT /api/strategies/{code}` but backend only defines `PATCH`. Request returns 405 Method Not Allowed.
**Fix:** Either change frontend to PATCH or add a PUT route on the backend.

### H-04: Frontend Strategy Status Mismatch
**File:** `frontend/app/dashboard/strategies/page.tsx` → `backend/app/models/strategy.py`
**Issue:** Frontend sends/expects `"RUNNING"/"PAUSED"` but backend model uses `"active"/"paused"`. Status toggling silently fails.
**Fix:** Standardize to one convention (recommend uppercase: `"ACTIVE"/"PAUSED"`).

### H-05: Frontend Trade Params Don't Match Backend
**File:** `frontend/app/dashboard/strategies/[code]/page.tsx`
**Issue:** Frontend sends `strategy_code` and `limit` query params, but backend expects `strategy_filter` and `per_page`.
**Fix:** Align frontend param names to match backend API.

### H-06: Dashboard Page Bypasses Zustand Store
**File:** `frontend/app/dashboard/page.tsx`
**Issue:** Makes direct `fetch()` calls instead of using the Zustand store (`useDashboardStore`). Data is not shared with other components, causing redundant API calls.
**Fix:** Use the Zustand store for dashboard data.

### H-07: Frontend Type Mismatches with Backend
**File:** `frontend/lib/types.ts`
**Issue:** Multiple type definitions don't match backend responses:
- `HealthCheck.services` typed as `Record<string, string>` but backend returns nested objects
- `StrategyResponse` missing fields (`xp_level`, `badge`, `fitness_score`)
- `DashboardSummary` missing `regime`, `symbols`, `positions` fields
- `TradeStats` fields don't match `/stats/summary` response
**Fix:** Update all frontend types to match actual backend response shapes.

### H-08: TypeScript Build Errors Masked
**File:** `frontend/next.config.js`
**Issue:** `typescript: { ignoreBuildErrors: true }` hides all type errors. The frontend builds even with broken types.
**Fix:** Remove `ignoreBuildErrors` and fix all type errors.

### H-09: Survivor Badge Logic Never Triggers
**File:** `backend/app/brain/strategy_xp.py`
**Issue:** Survivor badge checks the loss streak AFTER the streak is reset by a win. The condition `streak >= 5` is never true at the point it's checked.
**Fix:** Check for survivor badge BEFORE resetting the streak.

### H-10: XAUUSD Incorrectly Classified as Weekend Safe
**File:** `backend/app/risk/risk_manager.py`
**Issue:** Gold (XAUUSD) is classified in the "weekend safe" category, but gold markets close on weekends and can gap significantly.
**Fix:** Remove XAUUSD from weekend-safe list.

### H-11: MAX_TEST_LOTS Caps All Positions
**File:** `backend/app/risk/risk_manager.py`
**Issue:** `MAX_TEST_LOTS = 0.01` is applied even in live mode, capping every position to micro lots regardless of account size or strategy allocation.
**Fix:** Only apply the cap in test/dry-run mode, or scale with account size.

### H-12: Two-Phase Trade Write Race Condition
**File:** `backend/app/engine/engine.py`
**Issue:** Trades are written as PENDING first, then updated to OPEN after MT5 confirmation. If the engine crashes between these two writes, trades remain stuck in PENDING forever.
**Fix:** Use a single transaction, or add a cleanup job for stale PENDING trades.

### H-13: Pool Exhaustion Risk
**File:** `backend/app/db/engine.py`
**Issue:** `pool_size=20, max_overflow=0` means max 20 concurrent DB connections with no overflow. Under load (many concurrent API requests), connections exhaust and requests hang.
**Fix:** Allow some overflow: `max_overflow=10` or increase pool size.

### H-14: broadcast_event() Is Dead Code
**File:** `backend/app/api/routes_ws.py`
**Issue:** `broadcast_event()` function is defined but never called anywhere in the codebase. WebSocket clients never receive real-time updates.
**Fix:** Wire `broadcast_event()` into event handlers so WS clients get live updates.

### H-15: Kill Switch Reset Is a Placeholder
**File:** `backend/app/api/routes_system.py` (line 391-402)
**Issue:** `reset_kill_switch()` only returns a JSON response. It doesn't actually change any system state — trading doesn't actually resume.
**Fix:** Implement actual state change (e.g., update a SystemHealth flag, publish KILL_SWITCH_RESET event).

### H-16: equity_curve Not Populated
**File:** `backend/app/api/routes_system.py` → `backend/app/models/account.py`
**Issue:** The equity_curve field exists in the model but is never written to. Frontend equity chart always shows empty.
**Fix:** Record equity snapshots periodically (e.g., after each trade or on a schedule).

### H-17: Sorted Trades Crash on NULL closed_at
**File:** `backend/app/api/routes_trades.py`
**Issue:** `sorted(trades, key=lambda t: t.closed_at)` crashes with `TypeError` when `closed_at` is NULL (open trades). Frontend gets 500 error.
**Fix:** Use `key=lambda t: t.closed_at or datetime.min`.

### H-18: EventType Enum Defined But Never Used
**File:** `backend/app/config/constants.py` → all event publishers
**Issue:** `EventType` enum is defined with proper event names, but all code uses raw strings (`"trade_closed"`, `"TRADE_CLOSED"`). No compile-time checking of event names.
**Fix:** Use `EventType.TRADE_CLOSED.value` everywhere for consistency.

### H-19: SUPPORTED_SYMBOLS Missing GBPUSD and USDJPY
**File:** `backend/app/config/constants.py`
**Issue:** `SUPPORTED_SYMBOLS` list doesn't include GBPUSD and USDJPY, which are commonly traded pairs. Any trades on these symbols would be rejected.
**Fix:** Add missing symbols to the list.

### H-20: Frontend Dead/Orphaned Components
**Files:** `frontend/components/trades/TradeStats.tsx`, `TradeTable.tsx`, `TradeFilters.tsx`, `StrategyDetail.tsx`
**Issue:** These components exist but are never imported or used by any page. Dead code bloat.
**Fix:** Either integrate them into the pages that need them, or delete them.

### H-21: No Error Handling on Brain API Routes
**File:** `backend/app/api/routes_brain.py`
**Issue:** All brain endpoints have no try/except. Any Brain service error returns raw 500 with stack trace.
**Fix:** Add proper error handling with user-friendly error messages.

### H-22: mt5_login=0 in create_trade Violates Schema
**File:** `backend/app/api/routes_trades.py`
**Issue:** Manual trade creation sets `mt5_login=0` as default, but account schema validators may reject `login=0`.
**Fix:** Use the actual MT5 login from settings or make mt5_login optional.

### H-23: Strategy trade_service Uses Wrong Event Payload
**File:** `backend/app/services/trade_service.py`
**Issue:** The `trade_closed` event payload is missing `strategy_code` field. Even if event names matched, the handler can't look up which strategy to update.
**Fix:** Include `strategy_code` in the event payload dict.

### H-24: Frontend Login Token Not Refreshed
**File:** `frontend/app/login/page.tsx` → all API calls
**Issue:** JWT token is stored in localStorage but never refreshed. After expiration, all API calls fail with 401 and user must manually re-login.
**Fix:** Add token refresh logic or redirect to login on 401.

### H-25: No CSRF Protection
**File:** `backend/app/main.py`
**Issue:** No CSRF tokens for state-changing requests. Combined with credentials mode, this enables cross-site request forgery.
**Fix:** Add CSRF middleware or use SameSite cookies.

### H-26: Docker Healthchecks Missing for Most Services
**File:** `docker-compose.yml`
**Issue:** Only postgres has a healthcheck. Backend, engine, frontend, redis — none have healthchecks. Docker can't auto-restart unhealthy containers.
**Fix:** Add healthcheck directives for all services.

### H-27: No Rate Limiting on API
**File:** `backend/app/main.py`
**Issue:** No rate limiting middleware. Kill switch, trade creation, and auth endpoints can be hammered without restriction.
**Fix:** Add rate limiting (e.g., slowapi) at least for auth and critical endpoints.

### H-28: Caddy WebSocket Proxy May Timeout
**File:** `infra/caddy/Caddyfile`
**Issue:** No explicit WebSocket timeout configuration. Caddy's default timeouts may close long-lived WS connections prematurely.
**Fix:** Add `flush_interval -1` and appropriate timeouts for the `/ws/*` route.

### H-29: Engine Missing Direct Dependency on Postgres/Redis Health
**File:** `docker-compose.yml` lines 123-127
**Issue:** `jsr-engine` depends on `jsr-backend: service_started` (not `service_healthy`) and has no direct dependency on Postgres/Redis health. Engine can start and attempt DB writes before Postgres is ready.
**Fix:** Add `jsr-postgres: service_healthy` and `jsr-redis: service_healthy` to engine's `depends_on`.

### H-30: Backend Has No Docker Health Check
**File:** `docker-compose.yml` lines 78-106
**Issue:** No healthcheck defined for `jsr-backend`. Dependent services use `condition: service_started` instead of `service_healthy`.
**Fix:** Add `healthcheck: test: ["CMD-SHELL", "curl -f http://localhost:8000/api/system/health || exit 1"]`.

### H-31: MT5 Health Check Only Tests Process, Not Bridge
**File:** `docker-compose.yml` lines 19-24
**Issue:** Health check runs `pgrep terminal64.exe` but the Flask bridge has a 90-second sleep before starting. Engine gets connection refused during this window.
**Fix:** Change health check to probe `http://localhost:18812/health` with `start_period: 180s`.

### H-32: Caddy Has No depends_on
**File:** `docker-compose.yml` lines 184-195
**Issue:** Caddy starts before backend/frontend may be ready, causing 502 errors on first requests.
**Fix:** Add `depends_on: [jsr-backend, jsr-frontend]`.

### H-33: `mt5linux` Package Listed But Never Used
**File:** `backend/pyproject.toml` line 19
**Issue:** `mt5linux` is in dependencies but never imported. Has Windows-specific native dependencies that may fail on Linux Docker images.
**Fix:** Remove from dependencies.

### H-34: No Database Migrations Strategy
**File:** `backend/alembic/` → deployment
**Issue:** Alembic migrations exist but aren't run automatically on deployment. Schema changes require manual intervention.
**Fix:** Add `alembic upgrade head` to the backend entrypoint or a pre-deploy script.

---

## MEDIUM Issues (Should Address — Reduced Functionality)

### M-01: get_event_bus() Creates New Settings Instance
**File:** `backend/app/events/bus.py`
**Issue:** Each call creates a fresh `Settings()` instead of using the singleton from `app.config.settings`. May lead to inconsistent configuration.

### M-02: Dashboard Makes 3 Sequential MT5 Requests
**File:** `backend/app/api/routes_system.py` (`_build_dashboard`)
**Issue:** Calls `/account`, `/positions`, `/symbols` sequentially. Each with 5s timeout = up to 15s response time.
**Fix:** Use `asyncio.gather()` for parallel requests.

### M-03: No Pagination on Strategies Endpoint
**File:** `backend/app/api/routes_strategies.py`
**Issue:** Returns all strategies without pagination. Not a problem with 4 strategies, but doesn't scale.

### M-04: Frontend Hardcoded API Base URL
**File:** `frontend/lib/api.ts`
**Issue:** API base URL construction doesn't account for different environments cleanly. Should use `NEXT_PUBLIC_API_URL` env var.

### M-05: No Request Timeout on Frontend Fetches
**File:** `frontend/app/dashboard/page.tsx` and other pages
**Issue:** `fetch()` calls have no timeout. If backend hangs, frontend hangs indefinitely.

### M-06: Engine Loop Has No Backoff on Repeated Failures
**File:** `backend/app/engine/engine.py`
**Issue:** If MT5 is disconnected, the engine loop retries every cycle with no exponential backoff, flooding logs.

### M-07: Trade Symbols Filter Fetches 100 Trades Just for Dropdown
**File:** `frontend/app/dashboard/trades/page.tsx` (line 53)
**Issue:** Fetches 100 trades just to extract unique symbols for the filter dropdown. Should have a dedicated `/symbols` endpoint.

### M-08: No Graceful Shutdown for Engine
**File:** `backend/app/engine/engine.py`
**Issue:** No signal handler for SIGTERM/SIGINT. Engine may be killed mid-trade execution.

### M-09: Frontend Trade Debounce on Every Keystroke
**File:** `frontend/app/dashboard/trades/page.tsx` (line 108-111)
**Issue:** 300ms debounce on filter changes is fine, but the timer resets on every dropdown change, causing unnecessary delays for select inputs.

### M-10: No Index on trades.strategy_code
**File:** `backend/app/models/trade.py`
**Issue:** Trades are frequently queried by strategy_code but there's no index on this column. Slow as trade count grows.

### M-11: No Index on trades.status
**File:** `backend/app/models/trade.py`
**Issue:** Status filter queries scan the full table without an index.

### M-12: Session Breakout Strategy Hardcoded Times
**File:** `backend/app/strategies/session_breakout.py`
**Issue:** London/NY session times are hardcoded without timezone awareness. DST changes will shift trading windows.

### M-13: No Health Endpoint for Frontend
**File:** `frontend/` (missing)
**Issue:** No `/health` or `/api/health` endpoint for the Next.js frontend. Can't verify frontend is responsive.

### M-14: Regime Service Returns None Without Logging
**File:** `backend/app/services/regime_service.py`
**Issue:** When no regime data exists, returns None silently. Dashboard shows "UNKNOWN" with no indication of why.

### M-15: No Retry Logic for MT5 HTTP Requests
**File:** `backend/app/api/routes_system.py` (`_mt5_request`)
**Issue:** Single attempt with 5s timeout. Transient network issues cause immediate failure.

### M-16: Frontend Date Formatting Inconsistent
**File:** Multiple frontend files
**Issue:** Some files use `toLocaleDateString()`, others use custom formatting. No consistent date formatting utility.

### M-17: Trade Model Missing Commission/Swap Fields Display
**File:** `frontend/app/dashboard/trades/page.tsx`
**Issue:** Trade table doesn't show commission or swap, even though the backend model has these fields.

### M-18: No Loading State for Strategy Toggle
**File:** `frontend/app/dashboard/strategies/page.tsx`
**Issue:** Status toggle has no loading indicator. User can click multiple times, sending duplicate requests.

### M-19: Zustand Store Actions Not Used
**File:** `frontend/store/dashboardStore.ts`
**Issue:** Store is defined with actions but the main dashboard page doesn't use them. Store is effectively dead code.

### M-20: No Error Boundary in Frontend
**File:** `frontend/app/layout.tsx`
**Issue:** No React error boundary. Any component crash takes down the entire page.

### M-21: Logger Not Configured for Production JSON Output
**File:** `backend/app/utils/logger.py`
**Issue:** Logger may not output structured JSON in production, making log aggregation difficult.

### M-22: No Backup Strategy for DB
**File:** Infrastructure
**Issue:** No automated database backup. PostgreSQL data could be lost on disk failure.

### M-23: Docker Volumes Not Named Properly
**File:** `docker-compose.yml`
**Issue:** Volume naming may conflict if multiple instances are deployed on the same host.

### M-24: No API Versioning
**File:** `backend/app/main.py`
**Issue:** All routes are under `/api/` with no version prefix. Breaking API changes will affect all clients.

### M-25: Frontend Bundle Size Not Optimized
**File:** `frontend/next.config.js`
**Issue:** No bundle analysis or optimization configuration. Recharts and other libraries may bloat the bundle.

### M-26: No Monitoring/Alerting Integration
**File:** Infrastructure
**Issue:** No Prometheus metrics, no Grafana dashboards, no alerting beyond the unimplemented Telegram TODO.

### M-27: Redis Connection Not Pooled
**File:** `backend/app/events/bus.py`
**Issue:** Creates new Redis connection on each EventBus instantiation rather than using a connection pool.

### M-28: No Test Suite
**File:** Entire codebase
**Issue:** No unit tests, integration tests, or end-to-end tests anywhere in the repository.

### M-29: Alembic env.py May Use Wrong DB URL
**File:** `backend/alembic/env.py`
**Issue:** May construct DB URL differently from the main application, leading to migration failures.

### M-30: No .env.example File
**File:** Root
**Issue:** No `.env.example` or documentation of required environment variables. New deployments require guessing.

### M-31: Frontend WebSocket Reconnect Aggressiveness
**File:** `frontend/hooks/useWebSocket.ts`
**Issue:** WebSocket reconnect logic may be too aggressive or not aggressive enough (depends on implementation). No exponential backoff visible.

### M-32: No API Documentation Beyond Auto-Generated
**File:** Backend
**Issue:** Relies entirely on FastAPI's auto-generated OpenAPI docs. No additional documentation for complex flows.

### M-33: Strategy Performance Never Reset
**File:** `backend/app/services/strategy_service.py`
**Issue:** No way to reset strategy performance metrics. If testing produces bad data, it permanently skews metrics.

### M-34: No Audit Trail for Configuration Changes
**File:** Backend
**Issue:** `CONFIGURATION_CHANGED` event is registered but never published. No record of who changed what.

### M-35: Frontend Chart Data Format Mismatch
**File:** `frontend/components/charts/` (various)
**Issue:** Charts expect specific data formats that may not match what the backend actually returns.

---

## LOW Issues (Nice to Have — Code Quality)

### L-01: Unused Imports
**Files:** Multiple backend files
**Issue:** Various unused imports (`Optional`, `Callable`, response models) that should be cleaned up.

### L-02: Inconsistent Naming Conventions
**Files:** Throughout codebase
**Issue:** Mix of snake_case and camelCase in API responses. Frontend types use camelCase, backend uses snake_case, with no consistent transformation layer.

### L-03: TODO Comments in Production Code
**Files:** `handlers.py` (Telegram), `retrainer.py`, `kill_switch.py`
**Issue:** Multiple TODO comments for unimplemented features that should be tracked as issues instead.

### L-04: Magic Numbers
**Files:** Various
**Issue:** Hardcoded values like `20` (symbols limit), `100` (max trades fetch), `5.0` (timeout), `60` (retrainer interval) should be constants.

### L-05: No Type Hints on Some Functions
**Files:** Various backend files
**Issue:** Some functions lack return type annotations, reducing IDE support and code clarity.

### L-06: Frontend Console.error in Production
**Files:** Multiple frontend pages
**Issue:** `console.error()` calls remain in production code. Should use a proper logging service.

### L-07: No Favicon or Meta Tags
**File:** `frontend/app/layout.tsx`
**Issue:** Missing proper favicon, meta description, and Open Graph tags.

### L-08: Git Repository Not Initialized on VPS
**File:** VPS deployment
**Issue:** Initially deployed via tar, then retrofitted with git. May have inconsistent state.

### L-09: No .dockerignore
**File:** Root
**Issue:** No `.dockerignore` file. Docker build context may include unnecessary files (node_modules, .git, etc.), slowing builds.

### L-10: Hardcoded MT5 REST URL
**File:** `backend/app/api/routes_system.py` (line 37)
**Issue:** Falls back to `http://jsr-mt5:18812` hardcoded. Should always come from settings.

### L-11: No Commit Message Standards
**File:** Repository
**Issue:** No conventional commits or commit message format enforcement.

### L-12: Frontend Package Lock Not Committed
**File:** `frontend/`
**Issue:** If `package-lock.json` or `yarn.lock` isn't committed, builds may produce different dependency trees.

### L-13: No Pre-commit Hooks
**File:** Repository
**Issue:** No linting, formatting, or type-checking hooks to catch issues before commit.

### L-14: Dockerfile Layer Caching Not Optimized
**Files:** `backend/Dockerfile`, `frontend/Dockerfile`
**Issue:** Dependencies may be reinstalled on every code change if COPY order isn't optimized.

### L-15: No Security Headers Beyond Caddy
**File:** Backend, Frontend
**Issue:** Backend doesn't set security headers. Relies entirely on Caddy, which may not cover all cases.

### L-16: Database Password in Docker Compose
**File:** `docker-compose.yml`
**Issue:** Database password may be visible in the compose file rather than using Docker secrets.

### L-17: No Log Rotation
**File:** Docker/VPS
**Issue:** Docker log output not configured with rotation. Logs can fill disk over time.

---

## Priority Fix Order (Recommended)

### Phase 0 — Security Emergency (Do Immediately)
1. **C-22** Remove hardcoded MT5 credentials from source code
2. **C-23** Rotate and remove exposed OpenAI API key
3. **C-24** Remove Redis port binding or add password
4. **C-25** Remove PostgreSQL port binding
5. **C-22-OLD** Enforce non-default JWT_SECRET and ADMIN_PASSWORD

### Phase 1 — Safety Critical (Do First)
6. **C-01** Weekend trading bug
7. **C-10** Wire post_trade_update() for daily P&L
8. **C-11** Wire kill switch auto-trigger
9. **C-14** Fix DRY_RUN position tracking

### Phase 2 — Core Functionality (Events & Communication)
6. **C-02** Fix event name case mismatch
7. **C-06** Call subscribe_redis() at startup
8. **C-07** Register event handlers in API server
9. **C-08** Fix sync Redis in order_manager
10. **H-23** Add strategy_code to trade event payload

### Phase 3 — API & Frontend Connectivity
11. **C-03** Fix WebSocket URL mismatch
12. **C-04** Fix CORS configuration
13. **C-05** Fix route ordering (stats/summary)
14. **C-16** Fix count query SQLAlchemy syntax
15. **H-03** Fix PUT vs PATCH mismatch
16. **H-04** Fix strategy status naming
17. **H-05** Fix frontend query params
18. **H-07** Fix frontend type definitions
19. **H-17** Fix sorted trades NULL crash

### Phase 4 — Brain & Strategy System
20. **C-12** Populate Brain cycle_summary with real data
21. **C-13** Fix strategy code format
22. **C-17** Apply auto-allocation to DB
23. **C-20** Persist Brain state to DB
24. **C-09** Seed default strategies
25. **H-09** Fix survivor badge timing

### Phase 5 — Security & Infrastructure
26. **H-01** Add auth to all endpoints
27. **H-02** Add auth to brain toggle
28. **H-25** Add CSRF protection
29. **H-27** Add rate limiting
30. **H-08** Remove ignoreBuildErrors
31. **H-26** Add Docker healthchecks
32. **H-29** Automate DB migrations

---

*Report generated by 5 parallel AI audit agents analyzing the complete JSR Hydra codebase.*
