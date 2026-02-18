"""
PURPOSE: OpenAI GPT-powered trading intelligence.
Uses GPT-4o-mini for cost-efficient market analysis, trade review,
and strategy improvement suggestions.

NOT called every cycle -- called on specific triggers to save costs:
1. Every 15 minutes: Market analysis summary
2. On trade close: Trade review and lessons learned
3. Every hour: Strategy performance review
4. On regime change: Regime analysis and strategy recommendations
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List
import httpx

from app.utils.logger import get_logger

logger = get_logger("brain.llm")


class LLMBrain:
    """
    PURPOSE: GPT-powered trading intelligence layer for JSR Hydra Brain.

    Makes cost-efficient calls to OpenAI GPT-4o-mini for market analysis,
    trade review, strategy optimization, and regime change analysis.
    All calls are rate-limited internally to prevent excessive API usage.

    CALLED BY:
        - brain/brain.py (process_cycle, process_trade_result, regime change)
        - api/routes_brain.py (get insights, get stats)
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._api_key = api_key
        self._model = model
        self._base_url = "https://api.openai.com/v1/chat/completions"
        self._last_analysis_time = 0
        self._last_review_time = 0
        self._analysis_interval = 900  # 15 minutes
        self._review_interval = 3600   # 1 hour
        self._total_tokens_used = 0
        self._total_calls = 0
        self._insights_history: List[Dict] = []  # Rolling list of LLM insights
        self._max_insights = 50

        logger.info(
            "llm_brain_initialized",
            model=model,
            analysis_interval=self._analysis_interval,
            review_interval=self._review_interval,
        )

    async def _call_gpt(self, system_prompt: str, user_prompt: str, max_tokens: int = 500) -> Optional[str]:
        """
        PURPOSE: Make an async call to OpenAI API.

        Args:
            system_prompt: System role instruction for GPT.
            user_prompt: User message with data to analyze.
            max_tokens: Maximum response length.

        Returns:
            str or None: GPT response content, or error string on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._base_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                data = response.json()
                tokens_used = data.get("usage", {}).get("total_tokens", 0)
                self._total_tokens_used += tokens_used
                self._total_calls += 1

                logger.info(
                    "llm_call_success",
                    model=self._model,
                    tokens=tokens_used,
                    total_calls=self._total_calls,
                )

                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error("llm_api_http_error", status=e.response.status_code, detail=str(e)[:200])
            return f"[LLM Error: HTTP {e.response.status_code}]"
        except Exception as e:
            logger.error("llm_api_error", error=str(e)[:200])
            return f"[LLM Error: {str(e)[:100]}]"

    def _store_insight(self, insight: Dict) -> None:
        """Store an insight in the rolling history, trimming if needed."""
        self._insights_history.append(insight)
        if len(self._insights_history) > self._max_insights:
            self._insights_history = self._insights_history[-self._max_insights:]

    async def analyze_market(self, market_data: Dict) -> Optional[Dict]:
        """
        PURPOSE: Analyze current market conditions. Called every 15 minutes.

        Returns insights and recommendations based on current indicators,
        regime, and account state. Internally rate-limited to avoid
        excessive API calls.

        Args:
            market_data: Dict with symbols, indicators, regime, account info.

        Returns:
            Dict with type, timestamp, content, model, tokens_used or None if too soon.

        CALLED BY: brain/brain.py process_cycle (via asyncio.create_task)
        """
        now = time.time()
        if now - self._last_analysis_time < self._analysis_interval:
            return None  # Too soon
        self._last_analysis_time = now

        system_prompt = """You are an expert forex and commodities trader AI assistant.
You analyze market data and provide concise, actionable trading insights.
Keep responses under 200 words. Be specific about price levels and conditions.
Format: Start with a 1-line summary, then bullet points for key observations and recommendations."""

        user_prompt = f"""Analyze these current market conditions:

Symbols being traded: {', '.join(market_data.get('symbols', []))}

For each symbol:
{json.dumps(market_data.get('symbol_data', {}), indent=2, default=str)}

Current regime: {market_data.get('regime', 'Unknown')}
ADX: {market_data.get('adx', 'N/A')}
RSI: {market_data.get('rsi', 'N/A')}
Account balance: ${market_data.get('balance', 0):.2f}
Open positions: {market_data.get('open_positions', 0)}
Today's P&L: ${market_data.get('daily_pnl', 0):.2f}

What are the key things to watch? Any dangers? Best opportunities right now?"""

        response = await self._call_gpt(system_prompt, user_prompt)
        if response:
            insight = {
                "type": "market_analysis",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": response,
                "model": self._model,
                "tokens_used": self._total_tokens_used,
            }
            self._store_insight(insight)
            logger.info("llm_market_analysis_complete", content_length=len(response))
            return insight
        return None

    async def review_trade(self, trade_data: Dict) -> Optional[Dict]:
        """
        PURPOSE: Review a completed trade and extract lessons.

        Called when a trade closes. Provides analysis of what went right
        or wrong, a lesson learned, and a suggestion for improvement.

        Args:
            trade_data: Dict with symbol, direction, strategy, entry/exit prices,
                       profit, duration, SL/TP, RSI at entry, regime.

        Returns:
            Dict with type, timestamp, content, trade_symbol, trade_pnl or None.

        CALLED BY: brain/brain.py process_trade_result (via asyncio.create_task)
        """
        system_prompt = """You are a trading coach reviewing a completed trade.
Provide a brief analysis (under 150 words) of:
1. What went right or wrong
2. One specific lesson learned
3. One suggestion for improvement
Be constructive and specific. Reference actual numbers."""

        profit = trade_data.get('profit', 0)
        user_prompt = f"""Review this completed trade:

Symbol: {trade_data.get('symbol')}
Direction: {trade_data.get('direction')}
Strategy: {trade_data.get('strategy')}
Entry: {trade_data.get('entry_price')}
Exit: {trade_data.get('exit_price')}
P&L: ${profit:.2f}
Duration: {trade_data.get('duration_minutes', 0)} minutes
Stop Loss: {trade_data.get('sl_price')}
Take Profit: {trade_data.get('tp_price')}
RSI at entry: {trade_data.get('rsi_at_entry', 'N/A')}
Regime at entry: {trade_data.get('regime', 'N/A')}
Win/Loss: {'WIN' if profit > 0 else 'LOSS'}"""

        response = await self._call_gpt(system_prompt, user_prompt)
        if response:
            insight = {
                "type": "trade_review",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": response,
                "trade_symbol": trade_data.get('symbol'),
                "trade_pnl": profit,
            }
            self._store_insight(insight)
            logger.info(
                "llm_trade_review_complete",
                symbol=trade_data.get('symbol'),
                pnl=profit,
            )
            return insight
        return None

    async def hourly_strategy_review(self, strategy_stats: Dict) -> Optional[Dict]:
        """
        PURPOSE: Review overall strategy performance. Called every hour.

        Analyzes strategy statistics and suggests parameter adjustments,
        lot size changes, and whether to pause underperforming strategies.

        Args:
            strategy_stats: Dict with per-strategy performance metrics.

        Returns:
            Dict with type, timestamp, content or None if too soon.

        CALLED BY: brain/brain.py (periodic call via asyncio.create_task)
        """
        now = time.time()
        if now - self._last_review_time < self._review_interval:
            return None
        self._last_review_time = now

        system_prompt = """You are a quantitative trading system optimizer.
Review strategy performance and suggest specific parameter changes.
Be precise -- suggest exact numbers for thresholds.
Keep response under 250 words.
Format as: Strategy [X]: [observation]. Suggestion: [specific change]."""

        user_prompt = f"""Review these strategy performances over the last hour:

{json.dumps(strategy_stats, indent=2, default=str)}

For each strategy, suggest:
1. Should we adjust any parameters? (RSI thresholds, EMA periods, etc.)
2. Should we increase or decrease lot size?
3. Should we pause any strategy that's underperforming?
4. Any new patterns you notice?"""

        response = await self._call_gpt(system_prompt, user_prompt, max_tokens=600)
        if response:
            insight = {
                "type": "strategy_review",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": response,
            }
            self._store_insight(insight)
            logger.info("llm_strategy_review_complete", content_length=len(response))
            return insight
        return None

    async def analyze_regime_change(self, old_regime: str, new_regime: str, indicators: Dict) -> Optional[Dict]:
        """
        PURPOSE: Analyze a market regime change and its implications.

        Called when the regime detector identifies a shift. Explains what
        the change means for different strategies and what to watch for.

        Args:
            old_regime: Previous regime string.
            new_regime: New regime string.
            indicators: Current indicator values (rsi, adx, atr, ema_20, ema_50).

        Returns:
            Dict with type, timestamp, content, old_regime, new_regime or None.

        CALLED BY: brain/brain.py process_cycle (via asyncio.create_task)
        """
        system_prompt = """You are a market regime analyst. When market conditions shift,
explain what it means for different trading strategies and what to watch for.
Keep it under 150 words. Be actionable."""

        user_prompt = f"""Market regime just changed from {old_regime} to {new_regime}.

Current indicators:
RSI: {indicators.get('rsi', 'N/A')}
ADX: {indicators.get('adx', 'N/A')}
ATR: {indicators.get('atr', 'N/A')}
EMA20: {indicators.get('ema_20', 'N/A')}
EMA50: {indicators.get('ema_50', 'N/A')}

What does this regime change mean? Which strategies should be more/less aggressive?
Any specific price levels to watch?"""

        response = await self._call_gpt(system_prompt, user_prompt)
        if response:
            insight = {
                "type": "regime_analysis",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": response,
                "old_regime": old_regime,
                "new_regime": new_regime,
            }
            self._store_insight(insight)
            logger.info(
                "llm_regime_analysis_complete",
                old_regime=old_regime,
                new_regime=new_regime,
            )
            return insight
        return None

    def get_insights(self, limit: int = 20) -> List[Dict]:
        """
        PURPOSE: Get recent LLM insights, newest first.

        Args:
            limit: Maximum number of insights to return.

        Returns:
            List of insight dicts.

        CALLED BY: api/routes_brain.py /llm-insights endpoint
        """
        return list(reversed(self._insights_history[-limit:]))

    def get_stats(self) -> Dict:
        """
        PURPOSE: Get LLM usage statistics.

        Returns:
            Dict with total_calls, total_tokens_used, estimated_cost_usd,
            model, and insights_count.

        CALLED BY: api/routes_brain.py /llm-insights endpoint
        """
        return {
            "total_calls": self._total_calls,
            "total_tokens_used": self._total_tokens_used,
            "estimated_cost_usd": round(self._total_tokens_used * 0.00000015, 4),  # gpt-4o-mini pricing
            "model": self._model,
            "insights_count": len(self._insights_history),
        }
