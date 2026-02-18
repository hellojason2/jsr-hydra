"""
PURPOSE: Main trading orchestrator engine for JSR Hydra.

The core trading loop that coordinates all components: MT5 bridge, strategies,
risk management, event system, and database. Runs continuously, checking market
conditions and executing trades via strategy signals.

CALLED BY:
    - engine/engine_runner.py (entry point)
"""

import asyncio
import json
import signal
from datetime import datetime
from typing import Optional, List, Dict

from app.config.settings import settings
from app.bridge import create_bridge
from app.bridge.connector import MT5Connector
from app.bridge.data_feed import DataFeed
from app.bridge.order_manager import OrderManager
from app.bridge.account_info import AccountInfo
from app.events.bus import EventBus
from app.events.handlers import register_all_handlers
from app.db.engine import AsyncSessionLocal
from app.risk.kill_switch import KillSwitch
from app.risk.position_sizer import PositionSizer
from app.risk.risk_manager import RiskManager
from app.engine.regime_detector import RegimeDetector
from app.indicators.trend import ema, adx
from app.indicators.volatility import atr
from app.indicators.momentum import rsi
from app.strategies.base import BaseStrategy
from app.strategies.strategy_a import StrategyA
from app.strategies.strategy_b import StrategyB
from app.strategies.strategy_c import StrategyC
from app.strategies.strategy_d import StrategyD
from app.brain import get_brain
from app.utils.logger import get_logger
from app.utils import time_utils
from app.services.trade_service import TradeService
from app.services.strategy_service import StrategyService
from app.schemas.trade import TradeCreate
from app.models.account import MasterAccount
from app.models.trade import Trade as TradeModel
from sqlalchemy import select

logger = get_logger("engine.orchestrator")


TRADING_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

SYMBOL_CONFIGS = {
    "EURUSD": {
        "lot_size": 0.02,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
    },
    "GBPUSD": {
        "lot_size": 0.01,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
    },
    "USDJPY": {
        "lot_size": 0.01,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
    },
    "XAUUSD": {
        "lot_size": 0.01,
        "sl_atr_mult": 2.0,  # Gold needs wider stops
        "tp_atr_mult": 2.5,
    },
}


class TradingEngine:
    """
    PURPOSE: Main orchestrator for the JSR Hydra trading system.

    Coordinates all components including MT5 bridge, event bus, strategies,
    risk management, and database operations. Implements the main trading loop
    that checks market conditions and executes trades based on strategy signals.

    Runs ALL 4 strategies on ALL symbols simultaneously for maximum trade
    frequency.

    CALLED BY: engine_runner.py (entry point)

    Attributes:
        settings: Configuration settings
        _bridge: MT5 bridge components (connector, data_feed, order_manager, account_info)
        _event_bus: Event bus for inter-module communication
        _regime_detector: Market regime detector
        _risk_manager: Risk management orchestrator
        _strategies: Dict of {(symbol, strategy_code): strategy_instance}
        _is_running: Flag indicating if engine is running
        _loop_interval: Interval in seconds between main loop iterations
        _start_time: Timestamp when engine started
    """

    def __init__(self, settings_obj: settings.__class__ = None):
        """
        PURPOSE: Initialize TradingEngine with settings and components.

        Args:
            settings_obj: Optional Settings object (uses global if not provided)

        CALLED BY: engine_runner.py
        """
        self.settings = settings_obj or settings
        self._is_running = False
        self._loop_interval = 5  # 5 seconds between cycles for real trading
        self._start_time: Optional[datetime] = None
        self._symbols: List[str] = list(TRADING_SYMBOLS)
        # Track new candle detection per (symbol, timeframe) — not global
        self._last_candle_time: Dict[tuple, datetime] = {}  # {(symbol, timeframe): datetime}

        # Track open trades: mt5_ticket -> {trade_db_id, strategy_code, symbol, ...}
        self._open_trades: Dict[int, dict] = {}
        self._cached_master_id = None

        # Initialize bridge components
        self._bridge = None
        self._connector: Optional[MT5Connector] = None
        self._data_feed: Optional[DataFeed] = None
        self._order_manager: Optional[OrderManager] = None
        self._account_info: Optional[AccountInfo] = None

        # Initialize event bus
        self._event_bus = EventBus(self.settings.REDIS_URL)

        # Initialize regime detector
        self._regime_detector = RegimeDetector(adx_threshold=25.0)

        # Initialize risk management components (placeholder, no initial values)
        self._kill_switch: Optional[KillSwitch] = None
        self._position_sizer: Optional[PositionSizer] = None
        self._risk_manager: Optional[RiskManager] = None

        # Strategy pool: keyed by (symbol, strategy_code) for multi-symbol support
        self._strategies: Dict[str, BaseStrategy] = {}

        logger.info(
            "trading_engine_initialized",
            loop_interval=self._loop_interval,
            dry_run=self.settings.DRY_RUN,
            symbols=self._symbols
        )

    async def start(self) -> None:
        """
        PURPOSE: Start the trading engine and main loop.

        Sequence:
        1. Connect MT5 bridge (connector.connect())
        2. Connect EventBus to Redis
        3. Register event handlers
        4. Initialize risk management components
        5. Register strategies
        6. Start main trading loop
        7. Handle signals (SIGINT, SIGTERM) for graceful shutdown

        CALLED BY: engine_runner.py, main entry point
        """
        try:
            logger.info("trading_engine_starting")

            # 1. Create and connect MT5 bridge
            await self._setup_bridge()

            # 2. Connect event bus to Redis
            await self._event_bus.connect()
            logger.info("event_bus_connected")

            # 3. Register event handlers
            register_all_handlers(self._event_bus)
            logger.info("event_handlers_registered")

            # 4. Initialize risk management components
            self._init_risk_management()
            logger.info("risk_management_initialized")

            # 5. Register strategies
            self._register_strategies()
            logger.info("strategies_registered", count=len(self._strategies))

            # 6. Set running flag and record start time
            self._is_running = True
            self._start_time = datetime.utcnow()

            # Publish engine started event
            await self._event_bus.publish(
                event_type="ENGINE_STARTED",
                data={
                    "timestamp": self._start_time.isoformat(),
                    "dry_run": self.settings.DRY_RUN
                },
                source="engine.orchestrator",
                severity="INFO"
            )

            logger.info(
                "trading_engine_started",
                time=self._start_time.isoformat(),
                strategies=len(self._strategies)
            )

            # 7. Run main trading loop (blocking)
            await self._main_loop()

        except Exception as e:
            logger.error("trading_engine_startup_failed", error=str(e))
            await self.stop()
            raise

    async def stop(self) -> None:
        """
        PURPOSE: Graceful shutdown of the trading engine.

        Sequence:
        1. Set running flag to False
        2. Stop all strategies
        3. Close all open positions (optional, for risk management)
        4. Close MT5 bridge connection
        5. Disconnect EventBus from Redis
        6. Record final state and uptime

        CALLED BY: Signal handlers, error conditions, or explicit shutdown
        """
        try:
            logger.info("trading_engine_stopping")

            # Stop running flag
            self._is_running = False

            # Stop all strategies
            for strategy_code, strategy in self._strategies.items():
                try:
                    strategy.stop()
                    logger.info("strategy_stopped", code=strategy_code)
                except Exception as e:
                    logger.error(
                        "strategy_stop_error",
                        code=strategy_code,
                        error=str(e)
                    )

            # Publish shutdown event
            uptime = self.uptime_seconds
            await self._event_bus.publish(
                event_type="ENGINE_STOPPED",
                data={
                    "timestamp": datetime.utcnow().isoformat(),
                    "uptime_seconds": uptime
                },
                source="engine.orchestrator",
                severity="INFO"
            )

            # Disconnect bridge
            if self._connector:
                await self._connector.disconnect()
                logger.info("mt5_bridge_disconnected")

            # Disconnect event bus
            await self._event_bus.disconnect()
            logger.info("event_bus_disconnected")

            logger.info(
                "trading_engine_stopped",
                uptime_seconds=uptime
            )

        except Exception as e:
            logger.error("trading_engine_shutdown_error", error=str(e))

    async def _setup_bridge(self) -> None:
        """
        PURPOSE: Initialize and connect the MT5 bridge.

        Creates bridge components (connector, data_feed, order_manager, account_info)
        from factory function and establishes MT5 connection.

        CALLED BY: start()
        """
        try:
            bridge_settings = {
                "mt5_rest_url": self.settings.MT5_REST_URL,
                "redis_url": self.settings.REDIS_URL,
                "dry_run": self.settings.DRY_RUN,
                "max_test_lots": self.settings.MAX_TEST_LOTS,
            }

            # Create bridge components
            self._connector, self._data_feed, self._order_manager, self._account_info = (
                create_bridge(bridge_settings)
            )

            # Always connect to MT5 — we need real data
            await self._connector.connect()
            logger.info("mt5_bridge_connected")

            # Resolve trading symbols: filter TRADING_SYMBOLS to those available
            try:
                available_symbols = await self._data_feed.get_symbols()
                resolved = [s for s in TRADING_SYMBOLS if s in available_symbols]
                if resolved:
                    self._symbols = resolved
                else:
                    # Fallback: keep defaults, broker may still accept them
                    logger.warning("no_trading_symbols_found_in_broker", available=available_symbols)
                logger.info("trading_symbols_resolved", symbols=self._symbols, available=len(available_symbols))
            except Exception as e:
                logger.warning("symbol_resolution_failed", error=str(e), fallback=self._symbols)

            await self._event_bus.publish(
                event_type="MT5_CONNECTED",
                data={"dry_run": self.settings.DRY_RUN, "symbols": self._symbols},
                source="engine.orchestrator",
                severity="INFO"
            )

        except Exception as e:
            logger.error("bridge_setup_failed", error=str(e))
            raise

    def _init_risk_management(self) -> None:
        """
        PURPOSE: Initialize risk management components.

        Creates and configures kill switch, position sizer, and risk manager.

        CALLED BY: start()
        """
        try:
            # Create kill switch
            self._kill_switch = KillSwitch(
                order_manager=self._order_manager
            )

            # Create position sizer
            self._position_sizer = PositionSizer()

            # Create risk manager
            self._risk_manager = RiskManager(
                kill_switch=self._kill_switch,
                position_sizer=self._position_sizer,
                account_info=self._account_info
            )

            logger.info("risk_management_components_initialized")

        except Exception as e:
            logger.error("risk_management_init_failed", error=str(e))
            raise

    def _register_strategies(self) -> None:
        """
        PURPOSE: Initialize and register ALL 4 strategies for EACH trading symbol.

        Creates strategy instances per-symbol with symbol-specific lot sizes
        and aggressive parameters for high trade frequency.

        CALLED BY: start()
        """
        try:
            for symbol in self._symbols:
                sym_cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS["EURUSD"])
                lot_size = sym_cfg["lot_size"]

                # Strategy A — Trend Following (aggressive: fast EMAs, low ADX, M15, continuation)
                key_a = f"{symbol}_A"
                strategy_a = StrategyA(
                    data_feed=self._data_feed,
                    order_manager=self._order_manager,
                    event_bus=self._event_bus,
                    config={
                        'timeframe': 'M15',
                        'lookback': 200,
                        'default_lots': lot_size,
                        'ema_fast': 9,
                        'ema_slow': 21,
                        'adx_threshold': 15,
                        'allow_continuation': True,
                    }
                )
                strategy_a.start()
                self._strategies[key_a] = strategy_a

                # Strategy B — Mean Reversion Grid (loosened z-score)
                key_b = f"{symbol}_B"
                strategy_b = StrategyB(
                    data_feed=self._data_feed,
                    order_manager=self._order_manager,
                    event_bus=self._event_bus,
                    config={
                        'timeframe': 'M15',
                        'lookback': 100,
                        'default_lots': lot_size,
                        'grid_levels': 5,
                        'grid_spacing_pips': 50,
                        'z_score_threshold': 1.3,
                    }
                )
                strategy_b.start()
                self._strategies[key_b] = strategy_b

                # Strategy C — Session Breakout (much less strict)
                key_c = f"{symbol}_C"
                strategy_c = StrategyC(
                    data_feed=self._data_feed,
                    order_manager=self._order_manager,
                    event_bus=self._event_bus,
                    config={
                        'timeframe': 'M15',
                        'lookback': 100,
                        'default_lots': lot_size,
                        'lookback_bars': 12,
                        'breakout_atr_mult': 0.5,
                    }
                )
                strategy_c.start()
                self._strategies[key_c] = strategy_c

                # Strategy D — Momentum Scalper (aggressive: loose BB+RSI, M15)
                key_d = f"{symbol}_D"
                strategy_d = StrategyD(
                    data_feed=self._data_feed,
                    order_manager=self._order_manager,
                    event_bus=self._event_bus,
                    config={
                        'timeframe': 'M15',
                        'lookback': 100,
                        'default_lots': lot_size,
                        'bb_period': 14,
                        'bb_std': 1.5,
                        'rsi_oversold': 38,
                        'rsi_overbought': 62,
                    }
                )
                strategy_d.start()
                self._strategies[key_d] = strategy_d

                logger.info("strategies_registered_for_symbol", symbol=symbol, strategies=[key_a, key_b, key_c, key_d])

            logger.info("all_strategies_registered", total=len(self._strategies), strategies=list(self._strategies.keys()))

        except Exception as e:
            logger.error("strategy_registration_failed", error=str(e))
            raise

    async def _main_loop(self) -> None:
        """
        PURPOSE: Main trading loop. Runs every 5 seconds using real MT5 data.

        Multi-symbol design: iterates over ALL symbols, detects new candles
        per (symbol, timeframe), and runs ALL strategies for each symbol.

        Sequence per iteration:
        1. For each symbol: fetch tick data, H1 candles for indicators/regime
        2. Detect new candles per (symbol, timeframe)
        3. Run all strategies that have a new candle for their symbol+timeframe
        4. Enforce SL/TP on every trade (auto-calculate from ATR if missing)
        5. Log comprehensive JSON summary every cycle
        6. Sleep 5 seconds

        CALLED BY: start()
        """
        try:
            cycle_count = 0

            while self._is_running:
                cycle_count += 1
                cycle_start = datetime.utcnow()

                try:
                    # Check market hours
                    if not time_utils.is_market_open():
                        logger.debug(
                            "market_closed",
                            cycle=cycle_count,
                            weekday=cycle_start.weekday()
                        )
                        await asyncio.sleep(self._loop_interval)
                        continue

                    # Check for weekend
                    if time_utils.is_weekend():
                        logger.debug(
                            "weekend_detected",
                            cycle=cycle_count
                        )
                        await asyncio.sleep(self._loop_interval)
                        continue

                    all_signals_summary = {}
                    all_trades = []
                    all_risk_checks = []

                    # ========== LOOP OVER ALL SYMBOLS ==========
                    for symbol in self._symbols:
                        sym_cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS["EURUSD"])

                        # --- Fetch tick data for this symbol ---
                        tick_data = {"bid": None, "ask": None, "spread": None}
                        try:
                            tick_data = await self._data_feed.get_tick(symbol)
                        except Exception as e:
                            logger.warning("tick_fetch_failed", symbol=symbol, error=str(e))

                        # Fetch H1 candles for indicator computation and regime detection
                        indicator_values = {
                            "rsi": None, "adx": None, "atr": None,
                            "ema_20": None, "ema_50": None
                        }
                        regime = None

                        try:
                            candles_h1 = await self._data_feed.get_candles(symbol, "H1", count=200)
                            if not candles_h1.empty and len(candles_h1) >= 50:
                                close = candles_h1['close']
                                high = candles_h1['high']
                                low = candles_h1['low']

                                # Compute indicators
                                rsi_vals = rsi(close, period=14)
                                adx_vals = adx(high, low, close, period=14)
                                atr_vals = atr(high, low, close, period=14)
                                ema_20 = ema(close, 20)
                                ema_50 = ema(close, 50)

                                indicator_values = {
                                    "rsi": round(float(rsi_vals.iloc[-1]), 2) if not rsi_vals.empty else None,
                                    "adx": round(float(adx_vals.iloc[-1]), 2) if not adx_vals.empty else None,
                                    "atr": round(float(atr_vals.iloc[-1]), 4) if not atr_vals.empty else None,
                                    "ema_20": round(float(ema_20.iloc[-1]), 5) if not ema_20.empty else None,
                                    "ema_50": round(float(ema_50.iloc[-1]), 5) if not ema_50.empty else None,
                                }

                                # Detect regime
                                regime = self._regime_detector.detect_regime(candles_h1)

                        except Exception as e:
                            logger.warning("candle_indicator_fetch_failed", symbol=symbol, error=str(e))

                        # --- Detect new candles per (symbol, timeframe) ---
                        # Get strategies for this symbol
                        symbol_strategies = {
                            k: v for k, v in self._strategies.items()
                            if k.startswith(f"{symbol}_")
                        }

                        # Collect unique timeframes for this symbol's strategies
                        strategy_timeframes: Dict[str, List[str]] = {}  # tf -> [strategy_keys]
                        for strat_key, strategy in symbol_strategies.items():
                            tf = strategy._config.get('timeframe', 'H1')
                            strategy_timeframes.setdefault(tf, []).append(strat_key)

                        # Fetch candles per timeframe and detect new candles per (symbol, tf)
                        new_candle_for_tf: Dict[str, bool] = {}
                        for tf in strategy_timeframes:
                            candle_key = (symbol, tf)
                            try:
                                candles_tf = await self._data_feed.get_candles(symbol, tf, count=200)
                                if not candles_tf.empty and len(candles_tf) >= 2:
                                    latest_candle_time = candles_tf.index[-1]
                                    prev_time = self._last_candle_time.get(candle_key)
                                    if prev_time is None:
                                        new_candle_for_tf[tf] = True
                                        logger.info("initial_candle_recorded", symbol=symbol, timeframe=tf, time=str(latest_candle_time))
                                    elif latest_candle_time > prev_time:
                                        new_candle_for_tf[tf] = True
                                        logger.info("new_candle_detected", symbol=symbol, timeframe=tf, time=str(latest_candle_time))
                                    else:
                                        new_candle_for_tf[tf] = False
                                    self._last_candle_time[candle_key] = latest_candle_time
                                else:
                                    new_candle_for_tf[tf] = False
                            except Exception as e:
                                logger.warning("candle_fetch_for_tf_failed", symbol=symbol, timeframe=tf, error=str(e))
                                new_candle_for_tf[tf] = False

                        # --- Run strategies for this symbol ---
                        for strat_key, strategy in symbol_strategies.items():
                            tf = strategy._config.get('timeframe', 'H1')
                            if not new_candle_for_tf.get(tf, False):
                                all_signals_summary[strat_key] = "waiting_for_candle"
                                continue

                            try:
                                if not strategy.is_active:
                                    all_signals_summary[strat_key] = "inactive"
                                    continue

                                # Run strategy cycle to get signal
                                signal = await strategy.run_cycle(symbol)

                                if signal is None:
                                    all_signals_summary[strat_key] = "no_signal"
                                    continue

                                # --- ENFORCE SL/TP: auto-calculate from ATR if missing ---
                                sl_price = signal.stop_loss
                                tp_price = signal.take_profit
                                entry_price = signal.entry_price

                                if sl_price is None or sl_price <= 0 or tp_price is None or tp_price <= 0:
                                    # Need ATR for fallback calculation
                                    fallback_atr = indicator_values.get("atr")
                                    if fallback_atr and fallback_atr > 0:
                                        if sl_price is None or sl_price <= 0:
                                            if signal.direction == "BUY":
                                                sl_price = entry_price - (fallback_atr * sym_cfg["sl_atr_mult"])
                                            else:
                                                sl_price = entry_price + (fallback_atr * sym_cfg["sl_atr_mult"])
                                            logger.warning(
                                                "sl_auto_calculated",
                                                strategy=strat_key,
                                                symbol=symbol,
                                                sl=sl_price,
                                                atr=fallback_atr
                                            )
                                        if tp_price is None or tp_price <= 0:
                                            if signal.direction == "BUY":
                                                tp_price = entry_price + (fallback_atr * sym_cfg["tp_atr_mult"])
                                            else:
                                                tp_price = entry_price - (fallback_atr * sym_cfg["tp_atr_mult"])
                                            logger.warning(
                                                "tp_auto_calculated",
                                                strategy=strat_key,
                                                symbol=symbol,
                                                tp=tp_price,
                                                atr=fallback_atr
                                            )
                                    else:
                                        logger.warning(
                                            "cannot_auto_calculate_sl_tp_no_atr",
                                            strategy=strat_key,
                                            symbol=symbol
                                        )
                                        all_signals_summary[strat_key] = "skipped_no_sl_tp"
                                        continue

                                # Final validation: SL and TP must be positive
                                if sl_price <= 0 or tp_price <= 0:
                                    logger.warning(
                                        "invalid_sl_tp_after_calculation",
                                        strategy=strat_key,
                                        symbol=symbol,
                                        sl=sl_price,
                                        tp=tp_price
                                    )
                                    all_signals_summary[strat_key] = "invalid_sl_tp"
                                    continue

                                all_signals_summary[strat_key] = {
                                    "direction": signal.direction,
                                    "entry": entry_price,
                                    "sl": sl_price,
                                    "tp": tp_price,
                                }

                                # Pre-trade risk check
                                risk_check = await self._risk_manager.pre_trade_check(
                                    symbol=signal.symbol,
                                    direction=signal.direction,
                                    sl_distance=abs(entry_price - sl_price)
                                )

                                risk_check_info = {
                                    "strategy": strat_key,
                                    "approved": risk_check.approved,
                                    "reason": risk_check.reason,
                                    "position_size": risk_check.position_size,
                                    "risk_score": risk_check.risk_score,
                                }
                                all_risk_checks.append(risk_check_info)

                                if not risk_check.approved:
                                    logger.warning(
                                        "trade_rejected_by_risk_manager",
                                        strategy=strat_key,
                                        symbol=symbol,
                                        reason=risk_check.reason,
                                        cycle=cycle_count
                                    )
                                    await self._event_bus.publish(
                                        event_type="TRADE_REJECTED",
                                        data={
                                            "strategy": strat_key,
                                            "symbol": signal.symbol,
                                            "reason": risk_check.reason
                                        },
                                        source="engine.orchestrator",
                                        severity="WARNING"
                                    )
                                    continue

                                # Execute trade via order manager (use enforced SL/TP)
                                order_result = await self._order_manager.open_position(
                                    symbol=signal.symbol,
                                    direction=signal.direction,
                                    lots=risk_check.position_size,
                                    sl=sl_price,
                                    tp=tp_price,
                                    comment=f"JSR_{strat_key}"[:31]
                                )

                                if order_result is None:
                                    logger.warning(
                                        "order_execution_failed",
                                        strategy=strat_key,
                                        symbol=signal.symbol
                                    )
                                    continue

                                trade_info = {
                                    "strategy": strat_key,
                                    "symbol": symbol,
                                    "direction": signal.direction,
                                    "lots": risk_check.position_size,
                                    "ticket": order_result.get('ticket'),
                                    "sl": sl_price,
                                    "tp": tp_price,
                                }
                                all_trades.append(trade_info)

                                # Log trade execution
                                logger.info(
                                    "trade_executed",
                                    strategy=strat_key,
                                    symbol=signal.symbol,
                                    direction=signal.direction,
                                    lots=risk_check.position_size,
                                    ticket=order_result.get('ticket'),
                                    sl=sl_price,
                                    tp=tp_price,
                                    cycle=cycle_count
                                )

                                # Publish trade opened event
                                await self._event_bus.publish(
                                    event_type="TRADE_OPENED",
                                    data={
                                        "strategy": strat_key,
                                        "symbol": signal.symbol,
                                        "direction": signal.direction,
                                        "lots": risk_check.position_size,
                                        "entry_price": order_result.get('price'),
                                        "stop_loss": sl_price,
                                        "take_profit": tp_price,
                                        "ticket": order_result.get('ticket'),
                                        "timestamp": order_result.get('time', datetime.utcnow()).isoformat()
                                    },
                                    source="engine.orchestrator",
                                    severity="INFO"
                                )

                                # Notify Brain about the trade execution
                                try:
                                    brain = get_brain()
                                    brain.process_trade_result({
                                        "strategy": strat_key,
                                        "symbol": signal.symbol,
                                        "direction": signal.direction,
                                        "lots": risk_check.position_size,
                                        "entry_price": order_result.get('price'),
                                        "ticket": order_result.get('ticket'),
                                        "regime_at_entry": regime['regime'].value if regime else None,
                                    })
                                except Exception as brain_err:
                                    logger.warning("brain_trade_notify_error", error=str(brain_err))

                                # --- Record trade to database ---
                                try:
                                    async with AsyncSessionLocal() as session:
                                        master_id = await self._get_or_create_master_id(session)

                                        # Extract strategy code from strat_key (format: "SYMBOL_STRATEGY_X")
                                        strategy_code = strat_key.split('_', 1)[1] if '_' in strat_key else strat_key

                                        trade_create = TradeCreate(
                                            symbol=signal.symbol,
                                            direction=signal.direction,
                                            lots=risk_check.position_size,
                                            entry_price=order_result.get('price', entry_price),
                                            stop_loss=sl_price,
                                            take_profit=tp_price,
                                            strategy_code=strategy_code,
                                            reason=f"Signal from {strat_key}"
                                        )
                                        db_trade = await TradeService.create_trade(session, master_id, trade_create)

                                        # Set mt5_ticket and status to OPEN directly on model
                                        stmt = select(TradeModel).where(TradeModel.id == db_trade.id)
                                        result = await session.execute(stmt)
                                        trade_obj = result.scalar_one()
                                        trade_obj.mt5_ticket = order_result.get('ticket')
                                        trade_obj.status = "OPEN"
                                        await session.commit()

                                        ticket = order_result.get('ticket')
                                        if ticket:
                                            self._open_trades[ticket] = {
                                                'trade_id': db_trade.id,
                                                'strategy_code': strategy_code,
                                                'symbol': signal.symbol,
                                                'direction': signal.direction,
                                            }

                                        logger.info("trade_recorded_to_db", trade_id=str(db_trade.id), ticket=ticket)
                                except Exception as db_err:
                                    logger.warning("trade_db_recording_failed", error=str(db_err))

                            except Exception as e:
                                all_signals_summary[strat_key] = f"error: {str(e)}"
                                logger.error(
                                    "strategy_cycle_error",
                                    strategy=strat_key,
                                    symbol=symbol,
                                    error=str(e),
                                    cycle=cycle_count
                                )
                                await self._event_bus.publish(
                                    event_type="STRATEGY_ERROR",
                                    data={
                                        "strategy": strat_key,
                                        "symbol": symbol,
                                        "error": str(e)
                                    },
                                    source="engine.orchestrator",
                                    severity="ERROR"
                                )
                                continue

                    # ========== END SYMBOL LOOP ==========

                    # --- Check for closed positions ---
                    await self._check_closed_positions()

                    # --- Fetch account info ---
                    account_summary = {"balance": None, "equity": None, "drawdown": None}
                    try:
                        balance = await self._account_info.get_balance()
                        equity = await self._account_info.get_equity()
                        drawdown = ((balance - equity) / balance * 100.0) if balance > 0 else 0.0
                        account_summary = {
                            "balance": round(balance, 2),
                            "equity": round(equity, 2),
                            "drawdown": round(drawdown, 2),
                        }
                    except Exception as e:
                        logger.warning("account_info_fetch_failed", error=str(e))

                    # --- Log comprehensive JSON summary ---
                    cycle_summary = {
                        "event": "engine_cycle",
                        "cycle": cycle_count,
                        "symbols": self._symbols,
                        "signals": all_signals_summary,
                        "risk_checks": all_risk_checks,
                        "trades": all_trades,
                        "trades_this_cycle": len(all_trades),
                        "account": account_summary,
                    }
                    logger.info("engine_cycle", data=json.dumps(cycle_summary, default=str))

                    # ── Feed cycle data to the Brain ──
                    try:
                        brain = get_brain()
                        brain.process_cycle(cycle_summary)
                    except Exception as brain_err:
                        logger.warning("brain_process_cycle_error", error=str(brain_err))

                except Exception as e:
                    logger.error(
                        "main_loop_iteration_error",
                        cycle=cycle_count,
                        error=str(e)
                    )
                    await self._event_bus.publish(
                        event_type="SYSTEM_ERROR",
                        data={
                            "module": "engine.orchestrator",
                            "error": str(e),
                            "cycle": cycle_count
                        },
                        source="engine.orchestrator",
                        severity="ERROR"
                    )

                # Sleep before next iteration
                await asyncio.sleep(self._loop_interval)

        except Exception as e:
            logger.error("main_loop_fatal_error", error=str(e))
            raise

    async def _get_or_create_master_id(self, session) -> 'UUID':
        """
        PURPOSE: Get or create the master account for this engine.

        Queries MasterAccount by MT5_LOGIN from settings. If not found,
        creates a new one. Caches the result for subsequent calls.

        CALLED BY: Trade recording logic in _main_loop
        """
        if self._cached_master_id:
            return self._cached_master_id

        mt5_login = getattr(self.settings, 'MT5_LOGIN', 0) or 12345

        stmt = select(MasterAccount).where(MasterAccount.mt5_login == mt5_login)
        result = await session.execute(stmt)
        master = result.scalar_one_or_none()

        if not master:
            master = MasterAccount(mt5_login=mt5_login, broker="JSR", status="RUNNING")
            session.add(master)
            await session.commit()
            await session.refresh(master)

        self._cached_master_id = master.id
        return master.id

    async def _check_closed_positions(self) -> None:
        """
        PURPOSE: Check MT5 positions and detect closures (SL/TP hit).

        Compares tracked open trades against current MT5 positions.
        For any trade no longer open in MT5, records closure in the database,
        updates strategy performance metrics, and notifies the Brain.

        CALLED BY: _main_loop (each cycle)
        """
        if not self._open_trades:
            return

        try:
            mt5_positions = await self._order_manager.get_open_positions()
            open_tickets = {p.get('ticket') for p in mt5_positions}

            # Find trades that were open but are no longer in MT5
            closed_tickets = [t for t in self._open_trades if t not in open_tickets]

            for ticket in closed_tickets:
                trade_info = self._open_trades.pop(ticket)
                trade_id = trade_info['trade_id']
                strategy_code = trade_info['strategy_code']

                try:
                    # Try to get closed position details from MT5 history
                    position_data = None
                    try:
                        client = await self._connector._get_client()
                        resp = await client.get(f"/history/deal", params={"ticket": ticket})
                        if resp.status_code == 200:
                            position_data = resp.json()
                    except Exception:
                        pass

                    async with AsyncSessionLocal() as session:
                        # Get the trade to find its entry price
                        stmt = select(TradeModel).where(TradeModel.id == trade_id)
                        result = await session.execute(stmt)
                        trade_obj = result.scalar_one_or_none()

                        if trade_obj:
                            # Use position_data if available, otherwise estimate from current price
                            exit_price = 0.0
                            profit = 0.0
                            commission = 0.0
                            swap = 0.0

                            if position_data:
                                exit_price = position_data.get('price', 0.0)
                                profit = position_data.get('profit', 0.0)
                                commission = position_data.get('commission', 0.0)
                                swap = position_data.get('swap', 0.0)
                            else:
                                # Try to get from last known tick data
                                try:
                                    tick = await self._data_feed.get_tick(trade_info['symbol'])
                                    if trade_info['direction'] == 'BUY':
                                        exit_price = tick.get('bid', 0.0)
                                    else:
                                        exit_price = tick.get('ask', 0.0)
                                except Exception:
                                    pass

                            # Close the trade in DB
                            await TradeService.close_trade(
                                session, trade_id,
                                exit_price=exit_price,
                                profit=profit,
                                commission=commission,
                                swap=swap
                            )

                            # Update strategy performance
                            try:
                                # Re-fetch the closed trade
                                stmt = select(TradeModel).where(TradeModel.id == trade_id)
                                result = await session.execute(stmt)
                                closed_trade = result.scalar_one_or_none()
                                if closed_trade:
                                    await StrategyService.update_strategy_performance(
                                        session, strategy_code, closed_trade
                                    )
                            except Exception as perf_err:
                                logger.warning("strategy_perf_update_failed", error=str(perf_err))

                            # Notify Brain about the completed trade
                            try:
                                net_profit = profit - commission - swap
                                brain = get_brain()
                                brain.process_trade_result({
                                    "strategy": f"{trade_info['symbol']}_{strategy_code}",
                                    "symbol": trade_info['symbol'],
                                    "direction": trade_info['direction'],
                                    "entry_price": trade_obj.entry_price,
                                    "exit_price": exit_price,
                                    "profit": net_profit,
                                    "won": net_profit > 0,
                                    "ticket": ticket,
                                })
                            except Exception as brain_err:
                                logger.warning("brain_close_notify_error", error=str(brain_err))

                            logger.info(
                                "trade_closed_detected",
                                ticket=ticket,
                                strategy=strategy_code,
                                profit=profit,
                            )

                except Exception as close_err:
                    logger.error("trade_close_processing_failed", ticket=ticket, error=str(close_err))

        except Exception as e:
            logger.warning("position_monitoring_failed", error=str(e))

    @property
    def is_running(self) -> bool:
        """
        PURPOSE: Check if engine is currently running.

        Returns:
            bool: True if engine is active, False otherwise

        CALLED BY: External monitoring, status checks
        """
        return self._is_running

    @property
    def uptime_seconds(self) -> int:
        """
        PURPOSE: Calculate engine uptime in seconds.

        Returns:
            int: Number of seconds since engine started (0 if not running)

        CALLED BY: Status reporting, metrics collection
        """
        if self._start_time is None:
            return 0
        return int((datetime.utcnow() - self._start_time).total_seconds())

    @property
    def strategies(self) -> Dict[str, BaseStrategy]:
        """
        PURPOSE: Get dictionary of registered strategies.

        Returns:
            Dict[str, BaseStrategy]: Mapping of strategy code to instance

        CALLED BY: API endpoints, monitoring
        """
        return self._strategies
