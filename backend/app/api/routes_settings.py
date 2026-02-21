"""
PURPOSE: Settings API routes for JSR Hydra trading system.

Provides endpoints to read and update runtime trading settings such as
active trading symbols. Settings are persisted in Redis so both API and
engine processes share the same configuration.

Authentication required for all endpoints.

CALLED BY:
    - Frontend settings panel
"""

import json
from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.config.constants import SUPPORTED_SYMBOLS
from app.config.settings import settings
from app.core.rate_limit import limiter, READ_LIMIT, WRITE_LIMIT
from app.engine.engine import SYMBOL_CONFIGS, TRADING_SYMBOLS
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

TRADING_SYMBOLS_REDIS_KEY = "jsr:settings:trading_symbols"


def _get_redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


# ════════════════════════════════════════════════════════════════
# Trading Symbols
# ════════════════════════════════════════════════════════════════


@router.get("/trading-symbols")
@limiter.limit(READ_LIMIT)
async def get_trading_symbols(
    request: Request,
    _current_user: str = Depends(get_current_user),
):
    """
    PURPOSE: Return active trading symbols, available symbols, and per-symbol configs.

    Falls back to engine defaults (TRADING_SYMBOLS) when no Redis override exists.

    Returns:
        dict: {active_symbols, available_symbols, symbol_configs}

    CALLED BY: Frontend settings panel
    """
    try:
        r = _get_redis()
        raw = r.get(TRADING_SYMBOLS_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            active_symbols = data.get("active_symbols", TRADING_SYMBOLS)
        else:
            active_symbols = list(TRADING_SYMBOLS)
        return {
            "active_symbols": active_symbols,
            "available_symbols": SUPPORTED_SYMBOLS,
            "symbol_configs": SYMBOL_CONFIGS,
        }
    except Exception as e:
        logger.error("settings_route_failed", action="retrieve trading symbols", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve trading symbols")


class TradingSymbolsUpdate(BaseModel):
    active_symbols: list[str]


@router.patch("/trading-symbols")
@limiter.limit(WRITE_LIMIT)
async def update_trading_symbols(
    request: Request,
    body: TradingSymbolsUpdate,
    _current_user: str = Depends(get_current_user),
):
    """
    PURPOSE: Update the list of actively traded symbols.

    Validates that all requested symbols are in SUPPORTED_SYMBOLS and
    persists the selection to Redis for both API and engine processes.

    Returns:
        dict: {active_symbols, available_symbols, symbol_configs}

    CALLED BY: Frontend settings panel
    """
    if not body.active_symbols:
        raise HTTPException(status_code=400, detail="At least one trading symbol must be selected")

    invalid = [s for s in body.active_symbols if s not in SUPPORTED_SYMBOLS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported symbols: {', '.join(invalid)}. Allowed: {', '.join(SUPPORTED_SYMBOLS)}",
        )

    try:
        r = _get_redis()
        payload = json.dumps({
            "active_symbols": body.active_symbols,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        r.set(TRADING_SYMBOLS_REDIS_KEY, payload)
        return {
            "active_symbols": body.active_symbols,
            "available_symbols": SUPPORTED_SYMBOLS,
            "symbol_configs": SYMBOL_CONFIGS,
        }
    except Exception as e:
        logger.error("settings_route_failed", action="update trading symbols", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update trading symbols")
