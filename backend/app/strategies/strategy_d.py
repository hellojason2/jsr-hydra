"""
PURPOSE: Strategy D - Momentum Scalper using Bollinger Bands OR RSI.

STRATEGY LOGIC:
    - Generates signals when EITHER BB or RSI condition is met (not both required)
    - BUY when price < lower_band OR RSI < oversold threshold
    - SELL when price > upper_band OR RSI > overbought threshold
    - Momentum burst detection: large candle body + high body ratio triggers signal
    - Confidence based on RSI deviation from center (50)
    - Tighter stops: SL = 1.0 * ATR, TP = 1.5 * ATR
    - Designed for aggressive scalping on M15 timeframe

CALLED BY: engine/orchestrator.py → run_cycle()
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.config.constants import StrategyCode, OrderDirection
from app.bridge.data_feed import DataFeed
from app.bridge.order_manager import OrderManager
from app.events.bus import EventBus
from app.indicators.volatility import bollinger_bands, atr
from app.indicators.momentum import rsi
from app.strategies.base import BaseStrategy
from app.strategies.signals import StrategySignal
from app.utils.logger import get_logger


logger = get_logger("strategies.strategy_d")


class StrategyD(BaseStrategy):
    """
    PURPOSE: Momentum Scalper strategy using Bollinger Bands OR RSI.

    Aggressively scalps by firing on EITHER BB or RSI extremes (not both
    required). Also detects momentum bursts from large candle bodies.
    Uses tighter stops for quick in-and-out trades.

    CALLED BY: engine/orchestrator.py
    """

    def __init__(
        self,
        data_feed: DataFeed,
        order_manager: OrderManager,
        event_bus: EventBus,
        config: dict
    ):
        """
        PURPOSE: Initialize StrategyD with configuration and dependencies.

        Args:
            data_feed: DataFeed instance for market data access
            order_manager: OrderManager instance for trade execution
            event_bus: EventBus instance for event publishing
            config: Strategy configuration dictionary with keys:
                - bb_period (default 20): Bollinger Bands period
                - bb_std (default 2.0): Bollinger Bands standard deviation multiplier
                - rsi_period (default 14): RSI period
                - rsi_oversold (default 30): RSI oversold threshold
                - rsi_overbought (default 70): RSI overbought threshold
                - atr_period (default 14): ATR period for stop-loss
                - timeframe (default 'H1'): Candle timeframe
                - lookback (default 50): Number of candles to fetch
                - default_lots (default 1.0): Default lot size

        CALLED BY: Orchestrator initialization
        """
        super().__init__(
            code=StrategyCode.D,
            name="Momentum Scalper (BB | RSI)",
            data_feed=data_feed,
            order_manager=order_manager,
            event_bus=event_bus,
            config=config
        )

        # Set configuration with defaults
        self._bb_period = config.get('bb_period', 20)
        self._bb_std = config.get('bb_std', 2.0)
        self._rsi_period = config.get('rsi_period', 14)
        self._rsi_oversold = config.get('rsi_oversold', 30)
        self._rsi_overbought = config.get('rsi_overbought', 70)
        self._atr_period = config.get('atr_period', 14)
        self._timeframe = config.get('timeframe', 'H1')
        self._lookback = config.get('lookback', 50)

        logger.info(
            "strategy_d_initialized",
            bb_period=self._bb_period,
            bb_std=self._bb_std,
            rsi_period=self._rsi_period,
            rsi_oversold=self._rsi_oversold,
            rsi_overbought=self._rsi_overbought,
            atr_period=self._atr_period
        )

    def generate_signal(self, candles_df: pd.DataFrame) -> Optional[StrategySignal]:
        """
        PURPOSE: Generate trading signal based on BB OR RSI extremes, plus momentum bursts.

        Logic:
        1. Validate sufficient data availability
        2. Calculate Bollinger Bands, RSI, ATR
        3. EITHER condition triggers signal (not both required):
           - Price below lower BB → BUY
           - Price above upper BB → SELL
           - RSI below oversold → BUY
           - RSI above overbought → SELL
        4. Momentum burst: large candle body (>1.5x avg of last 5) with body_ratio > 0.6
        5. Tighter stops: SL = 1.0 * ATR, TP = 1.5 * ATR

        Args:
            candles_df: DataFrame with OHLCV columns (open, high, low, close, volume)
                       Index should be datetime

        Returns:
            StrategySignal: Trading signal if conditions met, or None if not

        CALLED BY: BaseStrategy.run_cycle()
        """
        try:
            # Validate minimum data points (max of bb_period and rsi_period + buffer)
            min_data = max(self._bb_period, self._rsi_period) + 5
            if len(candles_df) < min_data:
                logger.warning(
                    "insufficient_data_for_strategy_d",
                    available=len(candles_df),
                    required=min_data
                )
                return None

            # Extract OHLC data
            close = candles_df['close']
            high = candles_df['high']
            low = candles_df['low']
            open_price = candles_df['open']

            # Calculate Bollinger Bands
            upper_band, middle_band, lower_band = bollinger_bands(
                close,
                period=self._bb_period,
                std_dev=self._bb_std
            )

            # Calculate RSI
            rsi_values = rsi(close, period=self._rsi_period)

            # Calculate ATR for stop-loss
            atr_values = atr(high, low, close, self._atr_period)

            # Get latest values
            latest_close = close.iloc[-1]
            latest_open = open_price.iloc[-1]
            latest_high = high.iloc[-1]
            latest_low = low.iloc[-1]
            latest_upper_band = upper_band.iloc[-1]
            latest_middle_band = middle_band.iloc[-1]
            latest_lower_band = lower_band.iloc[-1]
            latest_rsi = rsi_values.iloc[-1]
            latest_atr = atr_values.iloc[-1]

            # Handle NaN values
            if (pd.isna(latest_upper_band) or pd.isna(latest_lower_band) or
                pd.isna(latest_middle_band) or pd.isna(latest_rsi) or pd.isna(latest_atr)):
                logger.debug(
                    "nan_values_in_indicators",
                    upper_band_nan=pd.isna(latest_upper_band),
                    lower_band_nan=pd.isna(latest_lower_band),
                    middle_band_nan=pd.isna(latest_middle_band),
                    rsi_nan=pd.isna(latest_rsi),
                    atr_nan=pd.isna(latest_atr)
                )
                return None

            signal_direction = None
            reasons = []

            # --- Check BB conditions (EITHER triggers) ---
            bb_buy = latest_close < latest_lower_band
            bb_sell = latest_close > latest_upper_band

            # --- Check RSI conditions (EITHER triggers) ---
            rsi_buy = latest_rsi < self._rsi_oversold
            rsi_sell = latest_rsi > self._rsi_overbought

            # --- Check momentum burst ---
            momentum_buy = False
            momentum_sell = False
            if len(candles_df) >= 6:
                current_body = abs(latest_close - latest_open)
                candle_range = latest_high - latest_low
                body_ratio = current_body / candle_range if candle_range > 0 else 0

                # Average body of last 5 candles (excluding current)
                recent_bodies = abs(close.iloc[-6:-1] - open_price.iloc[-6:-1])
                avg_body = recent_bodies.mean()

                if current_body > 1.5 * avg_body and body_ratio > 0.6:
                    if latest_close > latest_open:
                        momentum_buy = True
                    else:
                        momentum_sell = True

            # --- Determine signal direction ---
            buy_signals = []
            sell_signals = []

            if bb_buy:
                buy_signals.append(f"price {latest_close:.5f} < lower BB {latest_lower_band:.5f}")
            if rsi_buy:
                buy_signals.append(f"RSI {latest_rsi:.1f} < {self._rsi_oversold}")
            if momentum_buy:
                buy_signals.append("momentum burst (bullish)")

            if bb_sell:
                sell_signals.append(f"price {latest_close:.5f} > upper BB {latest_upper_band:.5f}")
            if rsi_sell:
                sell_signals.append(f"RSI {latest_rsi:.1f} > {self._rsi_overbought}")
            if momentum_sell:
                sell_signals.append("momentum burst (bearish)")

            if buy_signals and not sell_signals:
                signal_direction = OrderDirection.BUY
                reasons = buy_signals
                logger.info(
                    "scalper_buy_detected",
                    close=latest_close,
                    lower_band=latest_lower_band,
                    rsi=latest_rsi,
                    triggers=buy_signals
                )
            elif sell_signals and not buy_signals:
                signal_direction = OrderDirection.SELL
                reasons = sell_signals
                logger.info(
                    "scalper_sell_detected",
                    close=latest_close,
                    upper_band=latest_upper_band,
                    rsi=latest_rsi,
                    triggers=sell_signals
                )
            else:
                # No signal or conflicting signals
                return None

            # Tighter stops: SL = 1.0 * ATR, TP = 1.5 * ATR
            if signal_direction == OrderDirection.BUY:
                sl_price = latest_close - (latest_atr * 1.0)
                tp_price = latest_close + (latest_atr * 1.5)
            else:  # SELL
                sl_price = latest_close + (latest_atr * 1.0)
                tp_price = latest_close - (latest_atr * 1.5)

            # Ensure SL and TP are valid
            if sl_price <= 0 or tp_price <= 0:
                logger.warning(
                    "invalid_sl_tp_prices",
                    sl=sl_price,
                    tp=tp_price
                )
                return None

            # Calculate confidence based on RSI deviation from center (50)
            confidence = min(abs(latest_rsi - 50.0) / 50.0, 1.0)

            # Create and return signal
            reason_str = "Momentum scalp: " + "; ".join(reasons)
            signal = StrategySignal(
                direction=signal_direction,
                confidence=confidence,
                sl_price=sl_price,
                tp_price=tp_price,
                reason=reason_str,
                strategy_code=self._code.value
            )

            logger.info(
                "signal_generated",
                direction=signal_direction,
                confidence=confidence,
                sl=sl_price,
                tp=tp_price,
                rsi=latest_rsi,
                atr=latest_atr,
                triggers=reasons
            )

            return signal

        except Exception as e:
            logger.error(
                "generate_signal_error",
                error=str(e),
                error_type=type(e).__name__
            )
            return None

    def get_config(self) -> dict:
        """
        PURPOSE: Return the strategy's current configuration.

        Returns:
            dict: Configuration dictionary with all strategy parameters

        CALLED BY: API endpoints, configuration serialization
        """
        return {
            "bb_period": self._bb_period,
            "bb_std": self._bb_std,
            "rsi_period": self._rsi_period,
            "rsi_oversold": self._rsi_oversold,
            "rsi_overbought": self._rsi_overbought,
            "atr_period": self._atr_period,
            "timeframe": self._timeframe,
            "lookback": self._lookback,
            "default_lots": self._config.get('default_lots', 1.0),
        }
