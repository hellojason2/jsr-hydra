/**
 * API Client for JSR Hydra Trading System
 * Handles HTTP communication with backend
 */

import {
  LoginRequest,
  TokenResponse,
  DashboardSummary,
  TradeList,
  TradeResponse,
  StrategyResponse,
  StrategyUpdate,
  HealthCheck,
} from "./types";

const BASE_URL =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Helper function to fetch from API with auth header
 */
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;

  // Get token from localStorage if available
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("auth_token")
      : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    // Handle 401 Unauthorized
    if (response.status === 401) {
      if (typeof window !== "undefined") {
        localStorage.removeItem("auth_token");
        window.location.href = "/login";
      }
    }
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `API Error: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Authentication APIs
 */
export async function login(
  username: string,
  password: string
): Promise<TokenResponse> {
  return fetchApi<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

/**
 * Dashboard APIs
 */
export async function getDashboard(): Promise<DashboardSummary> {
  return fetchApi<DashboardSummary>("/api/dashboard");
}

/**
 * Trade APIs
 */
export interface TradeFilters {
  status?: "OPEN" | "CLOSED" | "PENDING";
  symbol?: string;
  strategy_code?: string;
  limit?: number;
  offset?: number;
}

export async function getTrades(filters: TradeFilters = {}): Promise<TradeList> {
  const params = new URLSearchParams();

  if (filters.status) params.append("status", filters.status);
  if (filters.symbol) params.append("symbol", filters.symbol);
  if (filters.strategy_code) params.append("strategy_code", filters.strategy_code);
  if (filters.limit) params.append("limit", filters.limit.toString());
  if (filters.offset) params.append("offset", filters.offset.toString());

  const query = params.toString();
  const endpoint = `/api/trades${query ? `?${query}` : ""}`;

  return fetchApi<TradeList>(endpoint);
}

export async function getTrade(tradeId: string): Promise<TradeResponse> {
  return fetchApi<TradeResponse>(`/api/trades/${tradeId}`);
}

/**
 * Strategy APIs
 */
export async function getStrategies(): Promise<StrategyResponse[]> {
  return fetchApi<StrategyResponse[]>("/api/strategies");
}

export async function getStrategy(code: string): Promise<StrategyResponse> {
  return fetchApi<StrategyResponse>(`/api/strategies/${code}`);
}

export async function updateStrategy(
  code: string,
  data: StrategyUpdate
): Promise<StrategyResponse> {
  return fetchApi<StrategyResponse>(`/api/strategies/${code}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

/**
 * Kill Switch APIs
 */
export async function triggerKillSwitch(): Promise<void> {
  return fetchApi<void>("/api/risk/kill-switch", {
    method: "POST",
  });
}

export async function resetKillSwitch(): Promise<void> {
  return fetchApi<void>("/api/risk/kill-switch/reset", {
    method: "POST",
  });
}

/**
 * Health Check API
 */
export async function getHealth(): Promise<HealthCheck> {
  return fetchApi<HealthCheck>("/api/health");
}

export { BASE_URL };
