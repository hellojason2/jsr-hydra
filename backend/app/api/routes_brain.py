"""
PURPOSE: Brain API routes for JSR Hydra trading system.

Provides read-only endpoints to access the Brain's real-time cognitive state:
thoughts, market analysis, planned next moves, and per-strategy confidence scores.

No authentication required (for now) — these are read-only monitoring endpoints.

CALLED BY:
    - Frontend dashboard (polling or SSE)
    - External monitoring tools
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.brain import get_brain
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/brain", tags=["brain"])


# ════════════════════════════════════════════════════════════════
# Full Brain State
# ════════════════════════════════════════════════════════════════


@router.get("/state")
async def get_brain_state():
    """
    PURPOSE: Return full brain state including thoughts, analysis, next moves, and strategy scores.

    Returns:
        dict: Complete brain state snapshot

    CALLED BY: Frontend dashboard
    """
    brain = get_brain()
    return brain.get_state()


# ════════════════════════════════════════════════════════════════
# Recent Thoughts
# ════════════════════════════════════════════════════════════════


@router.get("/thoughts")
async def get_brain_thoughts(
    limit: int = Query(default=50, ge=1, le=100, description="Number of recent thoughts to return"),
):
    """
    PURPOSE: Return recent Brain thoughts, newest first.

    Args:
        limit: Maximum number of thoughts (1-100, default 50)

    Returns:
        dict: List of thought objects with timestamp, type, content, confidence, metadata

    CALLED BY: Frontend thought feed
    """
    brain = get_brain()
    thoughts = brain.get_thoughts(limit=limit)
    return {
        "thoughts": thoughts,
        "count": len(thoughts),
        "total": brain._cycle_count,
    }


# ════════════════════════════════════════════════════════════════
# Market Analysis
# ════════════════════════════════════════════════════════════════


@router.get("/analysis")
async def get_market_analysis():
    """
    PURPOSE: Return current market analysis (trend, momentum, volatility, regime).

    Returns:
        dict: Human-readable market read with raw indicator data

    CALLED BY: Frontend analysis panel
    """
    brain = get_brain()
    return brain.get_market_analysis()


# ════════════════════════════════════════════════════════════════
# Next Moves
# ════════════════════════════════════════════════════════════════


@router.get("/next-moves")
async def get_next_moves():
    """
    PURPOSE: Return what the Brain is watching for — planned next actions and triggers.

    Returns:
        dict: List of human-readable next move descriptions

    CALLED BY: Frontend next-moves panel
    """
    brain = get_brain()
    moves = brain.get_next_moves()
    return {
        "next_moves": moves,
        "count": len(moves),
    }


# ════════════════════════════════════════════════════════════════
# Strategy Scores
# ════════════════════════════════════════════════════════════════


@router.get("/strategy-scores")
async def get_strategy_scores():
    """
    PURPOSE: Return per-strategy confidence scores with reasoning.

    Returns:
        dict: Strategy code -> {name, confidence, reason, status, rl_preset, rl_expected}

    CALLED BY: Frontend strategy confidence panel
    """
    brain = get_brain()
    scores = brain.get_strategy_scores()
    return {
        "strategy_scores": scores,
        "count": len(scores),
    }


# ════════════════════════════════════════════════════════════════
# RL Stats
# ════════════════════════════════════════════════════════════════


@router.get("/strategy-xp")
async def get_strategy_xp():
    """
    PURPOSE: Return Pokemon-style XP/level data for all strategies.

    Returns:
        dict: Strategy code -> XP state with level, progress, badges, skills

    CALLED BY: Frontend strategy pages, XP bar components
    """
    brain = get_brain()
    return brain.get_strategy_xp()


@router.get("/rl-stats")
async def get_rl_stats():
    """
    PURPOSE: Return reinforcement learning statistics for the brain dashboard.

    Includes Thompson Sampling distributions, trade history stats,
    per-strategy confidence adjustments, exploration rate, regime performance,
    and current streaks.

    Returns:
        dict: Comprehensive RL statistics including:
            - distributions: Thompson Sampling Beta distributions per (strategy, regime)
            - total_trades_analyzed: Total trades processed by RL
            - total_reward: Cumulative RL reward
            - avg_reward: Average RL reward per trade
            - exploration_rate: Current exploration rate (0-1)
            - confidence_adjustments: Per-strategy RL confidence adjustments
            - trade_history_summary: Win rate and profit summary
            - regime_performance: Per-strategy per-regime performance matrix
            - streaks: Current win/loss streaks per strategy

    CALLED BY: Frontend RL dashboard panel
    """
    brain = get_brain()
    return brain.get_rl_stats()


# ════════════════════════════════════════════════════════════════
# LLM Insights
# ════════════════════════════════════════════════════════════════


@router.get("/llm-insights")
async def get_llm_insights():
    """
    PURPOSE: Return LLM-generated trading insights and usage statistics.

    Returns GPT-powered market analyses, trade reviews, strategy suggestions,
    and regime change analyses along with token usage and cost tracking.

    Returns:
        dict: {
            insights: List of LLM insight dicts (newest first),
            stats: {total_calls, total_tokens_used, estimated_cost_usd, model, insights_count}
        }

    CALLED BY: Frontend LLM insights panel
    """
    brain = get_brain()
    if brain._llm:
        return {
            "insights": brain._llm.get_insights(),
            "stats": brain._llm.get_stats(),
        }
    return {
        "insights": [],
        "stats": {
            "total_calls": 0,
            "total_tokens_used": 0,
            "estimated_cost_usd": 0,
            "model": "none",
            "insights_count": 0,
            "message": "LLM not configured -- set OPENAI_API_KEY to enable",
        },
    }


# ════════════════════════════════════════════════════════════════
# Auto-Allocation Status
# ════════════════════════════════════════════════════════════════


@router.get("/auto-allocation-status")
async def get_auto_allocation_status():
    """
    PURPOSE: Return auto-allocation engine status including fitness scores,
    rebalance history, and configuration.

    Returns:
        dict: {
            enabled: bool,
            trades_since_rebalance: int,
            trades_until_next: int,
            total_rebalances: int,
            last_fitness_scores: dict,
            last_allocations: dict,
            rebalance_history: list,
            config: dict,
        }

    CALLED BY: Frontend AllocationManager component
    """
    brain = get_brain()
    return brain.get_auto_allocation_status()


class AutoAllocationToggle(BaseModel):
    enabled: bool


@router.patch("/auto-allocation-status")
async def toggle_auto_allocation(body: AutoAllocationToggle):
    """
    PURPOSE: Enable or disable auto-allocation.

    Args:
        body: {"enabled": bool}

    Returns:
        dict: Updated auto-allocation status

    CALLED BY: Frontend AllocationManager toggle
    """
    brain = get_brain()
    brain.set_auto_allocation_enabled(body.enabled)
    return brain.get_auto_allocation_status()
