/**
 * TypeScript interfaces for JSR Hydra Trading System
 */

// Authentication
export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

// Account Information
export interface AccountInfo {
  balance: number;
  equity: number;
  margin_level: number;
  drawdown_pct: number;
  daily_pnl: number;
}

// Trade Related
export interface TradeResponse {
  id: string;
  master_id: string;
  strategy_id: string | null;
  idempotency_key: string | null;
  mt5_ticket: number | null;
  symbol: string;
  direction: string;
  lots: number;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  profit: number;
  commission: number;
  swap: number;
  net_profit: number;
  regime_at_entry: string | null;
  confidence: number | null;
  reason: string | null;
  status: string;
  is_simulated: boolean;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeCreate {
  symbol: string;
  direction: "BUY" | "SELL";
  lots: number;
  entry_price: number;
  strategy_code: string;
}

export interface TradeUpdate {
  exit_price?: number;
  status?: "OPEN" | "CLOSED";
}

export interface TradeList {
  trades: TradeResponse[];
  total: number;
  page: number;
  per_page: number;
}

export interface TradeStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
}

// Strategy Related
export interface StrategyResponse {
  code: string;
  name: string;
  status: "RUNNING" | "PAUSED" | "STOPPED";
  allocation_pct: number;
  win_rate: number;
  profit_factor: number;
  config: Record<string, unknown>;
}

export interface StrategyUpdate {
  status?: "RUNNING" | "PAUSED" | "STOPPED";
  allocation_pct?: number;
  config?: Record<string, unknown>;
}

// Market Regime
export interface RegimeResponse {
  regime: "TRENDING_UP" | "TRENDING_DOWN" | "RANGING" | "VOLATILE";
  confidence: number;
  conviction_score: number;
}

// Allocation
export interface AllocationResponse {
  strategy_code: string;
  allocation_pct: number;
  current_exposure: number;
  max_exposure: number;
}

export interface AllocationUpdate {
  strategy_code: string;
  allocation_pct: number;
}

// Dashboard Summary
export interface DashboardSummary {
  account: AccountInfo;
  trades: TradeStats;
  strategies: StrategyResponse[];
  regime: RegimeResponse;
  allocations: AllocationResponse[];
  timestamp: string;
}

// Health Check
export interface HealthCheck {
  status: "healthy" | "degraded" | "unhealthy";
  services: {
    database: boolean;
    websocket: boolean;
    broker_api: boolean;
  };
  version: string;
  uptime_seconds: number;
}

// Live Updates via WebSocket
export type LiveUpdateEventType =
  | "TRADE_OPENED"
  | "TRADE_CLOSED"
  | "PRICE_UPDATE"
  | "REGIME_CHANGE"
  | "ALLOCATION_CHANGE"
  | "STRATEGY_UPDATE"
  | "ACCOUNT_UPDATE"
  | "HEARTBEAT";

export interface LiveUpdate {
  event_type: LiveUpdateEventType;
  data: Record<string, unknown>;
  timestamp: string;
}

// WebSocket Messages
export interface WsMessage {
  type: string;
  payload?: Record<string, unknown>;
}
