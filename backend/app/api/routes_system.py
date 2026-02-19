"""
PURPOSE: System-level API routes for JSR Hydra trading system.

Provides endpoints for health checks, version information, dashboard summary,
kill switch controls, and system status monitoring.
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config.settings import settings
from app.db.engine import get_db
from app.models.account import MasterAccount
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.models.system import SystemHealth
from app.schemas import HealthCheck, VersionInfo, DashboardSummary
from app.schemas.account import AccountResponse
from app.schemas.strategy import StrategyMetrics
from app.services.regime_service import RegimeService
from app.utils.logger import get_logger
from app.version import get_version


logger = get_logger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

_startup_time = time.time()

MT5_REST_URL = getattr(settings, "MT5_REST_URL", "http://jsr-mt5:18812")


async def _mt5_request(path: str, method: str = "GET", json_data: dict = None, timeout: float = 5.0):
    """Make a request to the MT5 REST bridge."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(f"{MT5_REST_URL}{path}")
            else:
                resp = await client.post(f"{MT5_REST_URL}{path}", json=json_data)
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# Health Check (Public — no auth required)
# ════════════════════════════════════════════════════════════════


@router.get("/health", response_model=None, tags=["health"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check with all service statuses."""
    services = {}
    overall_status = "ok"

    # Check database
    try:
        await db.execute(select(1))
        services["postgres"] = {"status": "connected"}
    except Exception as e:
        services["postgres"] = {"status": "disconnected", "error": str(e)}
        overall_status = "degraded"

    # Check Redis
    try:
        from app.events.bus import get_event_bus
        bus = get_event_bus()
        if bus._redis:
            await bus._redis.ping()
            services["redis"] = {"status": "connected"}
        else:
            services["redis"] = {"status": "disconnected"}
            overall_status = "degraded"
    except Exception:
        services["redis"] = {"status": "disconnected"}
        overall_status = "degraded"

    # Check MT5
    mt5_data = await _mt5_request("/account")
    if mt5_data and "balance" in mt5_data:
        services["mt5"] = {
            "status": "connected",
            "account": mt5_data.get("login"),
            "broker": mt5_data.get("server"),
            "balance": mt5_data.get("balance"),
        }
    else:
        services["mt5"] = {"status": "disconnected"}
        overall_status = "degraded"

    # Version
    version_data = get_version()

    uptime = time.time() - _startup_time

    # Trading info
    trading = {
        "dry_run": settings.DRY_RUN,
        "system_status": "RUNNING",
    }

    # Open positions count
    positions = await _mt5_request("/positions")
    if positions and isinstance(positions, list):
        trading["open_positions"] = len(positions)
    else:
        trading["open_positions"] = 0

    return {
        "status": overall_status,
        "version": version_data.get("version", "1.0.0"),
        "codename": version_data.get("codename", "Hydra"),
        "uptime_seconds": round(uptime, 1),
        "services": services,
        "trading": trading,
    }


# ════════════════════════════════════════════════════════════════
# Version Info
# ════════════════════════════════════════════════════════════════


@router.get("/version", response_model=VersionInfo, tags=["version"])
async def get_system_version() -> VersionInfo:
    """Retrieve system version information."""
    version_data = get_version()
    return VersionInfo(
        version=version_data.get("version", "unknown"),
        codename=version_data.get("codename", "Hydra"),
        updated_at=version_data.get("updated_at", datetime.utcnow().isoformat()),
    )


# ════════════════════════════════════════════════════════════════
# Dashboard Summary — REAL DATA from MT5 + DB
# ════════════════════════════════════════════════════════════════


@router.get("/dashboard", response_model=None)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
):
    """Dashboard summary with real MT5 account data, positions, and strategy metrics."""
    try:
        return await _build_dashboard(db)
    except Exception as e:
        logger.error("dashboard_fatal_error", error=str(e))
        # Return a degraded but valid response instead of 500
        return {
            "account": None,
            "positions": [],
            "strategies": [],
            "recent_trades": [],
            "regime": None,
            "symbols": [],
            "system_status": "ERROR",
            "version": "unknown",
            "dry_run": settings.DRY_RUN,
            "uptime_seconds": round(time.time() - _startup_time, 1),
            "error": str(e),
        }


async def _build_dashboard(db: AsyncSession) -> dict:
    """Build dashboard data with graceful fallbacks for each section."""
    version_data = get_version()
    version = version_data.get("version", "1.0.0")

    # ── MT5 requests in parallel ──
    mt5_account, positions_raw, symbols_raw = await asyncio.gather(
        _mt5_request("/account"),
        _mt5_request("/positions"),
        _mt5_request("/symbols"),
    )

    account_data = None
    try:
        if mt5_account and "balance" in mt5_account:
            # Calculate drawdown
            peak_equity = mt5_account.get("equity", 0)
            try:
                stmt = select(MasterAccount).limit(1)
                result = await db.execute(stmt)
                db_account = result.scalar_one_or_none()
                if db_account and db_account.peak_equity:
                    peak_equity = max(db_account.peak_equity, mt5_account.get("equity", 0))
            except Exception:
                await db.rollback()  # master_accounts table may not exist yet

            drawdown_pct = 0.0
            if peak_equity > 0:
                drawdown_pct = max(0, (peak_equity - mt5_account.get("equity", 0)) / peak_equity * 100)

            account_data = {
                "login": mt5_account.get("login"),
                "server": mt5_account.get("server"),
                "balance": mt5_account.get("balance", 0),
                "equity": mt5_account.get("equity", 0),
                "margin": mt5_account.get("margin", 0),
                "free_margin": mt5_account.get("free_margin", 0),
                "margin_level": mt5_account.get("margin_level", 0),
                "profit": mt5_account.get("profit", 0),
                "currency": mt5_account.get("currency", "USD"),
                "leverage": mt5_account.get("leverage", 0),
                "peak_equity": peak_equity,
                "drawdown_pct": round(drawdown_pct, 2),
            }
    except Exception as e:
        logger.warning("dashboard_account_error", error=str(e))
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Positions (already fetched in parallel above) ──
    positions = positions_raw if isinstance(positions_raw, list) else []

    # ── Strategies from DB ──
    strategies_data = []
    try:
        stmt = select(Strategy)
        result = await db.execute(stmt)
        strategies = result.scalars().all()
        for s in strategies:
            strategies_data.append({
                "code": s.code,
                "name": s.name,
                "status": s.status,
                "allocation_pct": s.allocation_pct,
                "win_rate": s.win_rate,
                "profit_factor": s.profit_factor,
                "total_trades": s.total_trades,
                "total_profit": s.total_profit,
            })
    except Exception as e:
        logger.warning("dashboard_strategies_error", error=str(e))
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Recent trades from DB ──
    recent_trades = []
    try:
        stmt = select(Trade).order_by(Trade.created_at.desc()).limit(20)
        result = await db.execute(stmt)
        trades = result.scalars().all()
        for t in trades:
            recent_trades.append({
                "id": str(t.id),
                "symbol": t.symbol,
                "direction": t.direction,
                "lots": t.lots,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "profit": t.profit,
                "net_profit": t.net_profit,
                "status": t.status,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            })
    except Exception as e:
        logger.warning("dashboard_trades_error", error=str(e))
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Current regime from DB ──
    regime_data = None
    try:
        regime = await RegimeService.get_current_regime(db)
        if regime:
            regime_data = {
                "state": regime.regime.upper() if regime.regime else "UNKNOWN",
                "confidence": regime.confidence or 0,
                "conviction": regime.conviction_score or 0,
                "lastDetected": regime.detected_at.isoformat() if regime.detected_at else None,
            }
    except Exception as e:
        logger.warning("dashboard_regime_error", error=str(e))
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Available symbols (already fetched in parallel above) ──
    symbol_names = symbols_raw if isinstance(symbols_raw, list) else []

    # ── System status ──
    uptime = time.time() - _startup_time

    return {
        "account": account_data,
        "positions": positions,
        "strategies": strategies_data,
        "recent_trades": recent_trades,
        "regime": regime_data,
        "symbols": symbol_names[:20],  # First 20 symbols
        "system_status": "RUNNING",
        "version": version,
        "dry_run": settings.DRY_RUN,
        "uptime_seconds": round(uptime, 1),
    }


# ════════════════════════════════════════════════════════════════
# Live Tick Price
# ════════════════════════════════════════════════════════════════


@router.get("/tick/{symbol}")
async def get_tick(symbol: str):
    """Get live tick price for a symbol (public, no auth)."""
    data = await _mt5_request(f"/tick/{symbol}")
    if data and "bid" in data:
        return data
    raise HTTPException(status_code=404, detail=f"No tick data for {symbol}")


# ════════════════════════════════════════════════════════════════
# Positions (from MT5)
# ════════════════════════════════════════════════════════════════


@router.get("/positions")
async def get_positions():
    """Get open positions from MT5."""
    data = await _mt5_request("/positions")
    if isinstance(data, list):
        return data
    return []


# ════════════════════════════════════════════════════════════════
# Kill Switch Controls
# ════════════════════════════════════════════════════════════════


@router.post("/kill-switch", status_code=status.HTTP_200_OK)
async def trigger_kill_switch(
    reason: str = "Manual kill switch triggered",
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger kill switch — close all positions and halt trading."""
    logger.critical("kill_switch_triggered", reason=reason, triggered_by=current_user)

    # Close all open positions
    positions_closed = 0
    positions = await _mt5_request("/positions")
    if isinstance(positions, list):
        for pos in positions:
            ticket = pos.get("ticket")
            if ticket:
                result = await _mt5_request(f"/close/{ticket}", method="POST")
                if result and result.get("retcode") == 10009:
                    positions_closed += 1
                    logger.info("kill_switch_position_closed", ticket=ticket)

    # Publish event
    try:
        from app.events.bus import get_event_bus
        bus = get_event_bus()
        await bus.publish("KILL_SWITCH_TRIGGERED", {
            "reason": reason,
            "positions_closed": positions_closed,
            "triggered_by": current_user,
        })
    except Exception:
        pass

    return {
        "status": "halted",
        "reason": reason,
        "positions_closed": positions_closed,
        "timestamp": datetime.utcnow().isoformat(),
        "triggered_by": current_user,
    }


@router.post("/kill-switch/reset", status_code=status.HTTP_200_OK)
async def reset_kill_switch(
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reset kill switch and resume trading."""
    logger.info("kill_switch_reset", reset_by=current_user)

    # Publish KILL_SWITCH_RESET event via the shared Redis event bus.
    # The engine process subscribes to this channel and will call
    # kill_switch.reset(admin_override=True) upon receiving this event.
    try:
        from app.events.bus import get_event_bus
        bus = get_event_bus()
        await bus.publish("KILL_SWITCH_RESET", {
            "reset_by": current_user,
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.warning("kill_switch_reset_event_failed", error=str(e))

    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "reset_by": current_user,
    }
