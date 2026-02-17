/**
 * WebSocket Client for JSR Hydra Trading System
 * Handles real-time data streaming with auto-reconnect
 */

import { LiveUpdate } from "./types";

export type WsStatus = "connecting" | "connected" | "disconnected";

export interface WsConfig {
  url: string;
  heartbeatInterval?: number;
  maxReconnectAttempts?: number;
  baseReconnectDelay?: number;
  maxReconnectDelay?: number;
}

type MessageCallback = (message: LiveUpdate) => void;
type StatusCallback = (status: WsStatus) => void;

/**
 * WebSocket client with auto-reconnect and heartbeat
 */
export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private status: WsStatus = "disconnected";
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number;
  private reconnectDelay: number;
  private baseReconnectDelay: number;
  private maxReconnectDelay: number;
  private heartbeatInterval: number;
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;

  private messageCallbacks: Set<MessageCallback> = new Set();
  private statusCallbacks: Set<StatusCallback> = new Set();

  constructor(config: WsConfig) {
    this.url = config.url;
    this.maxReconnectAttempts = config.maxReconnectAttempts || 10;
    this.baseReconnectDelay = config.baseReconnectDelay || 1000; // 1 second
    this.maxReconnectDelay = config.maxReconnectDelay || 30000; // 30 seconds
    this.heartbeatInterval = config.heartbeatInterval || 30000; // 30 seconds
    this.reconnectDelay = this.baseReconnectDelay;
  }

  /**
   * Connect to WebSocket server
   */
  public connect(): void {
    if (this.status !== "disconnected") {
      return;
    }

    this.setStatus("connecting");

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log("[WS] Connected to", this.url);
        this.reconnectAttempts = 0;
        this.reconnectDelay = this.baseReconnectDelay;
        this.setStatus("connected");
        this.startHeartbeat();
      };

      this.ws.onmessage = (event) => {
        try {
          const message: LiveUpdate = JSON.parse(event.data);
          this.messageCallbacks.forEach((callback) => callback(message));
        } catch (error) {
          console.error("[WS] Failed to parse message:", error);
        }
      };

      this.ws.onerror = (error) => {
        console.error("[WS] Error:", error);
        this.setStatus("disconnected");
      };

      this.ws.onclose = () => {
        console.log("[WS] Disconnected");
        this.stopHeartbeat();
        this.setStatus("disconnected");
        this.attemptReconnect();
      };
    } catch (error) {
      console.error("[WS] Failed to create WebSocket:", error);
      this.setStatus("disconnected");
      this.attemptReconnect();
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  public disconnect(): void {
    this.stopHeartbeat();
    this.clearReconnectTimer();

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.setStatus("disconnected");
    this.reconnectAttempts = 0;
  }

  /**
   * Send message to server
   */
  public send(message: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(message));
      } catch (error) {
        console.error("[WS] Failed to send message:", error);
      }
    } else {
      console.warn("[WS] WebSocket is not connected");
    }
  }

  /**
   * Register callback for incoming messages
   */
  public onMessage(callback: MessageCallback): void {
    this.messageCallbacks.add(callback);
  }

  /**
   * Unregister message callback
   */
  public offMessage(callback: MessageCallback): void {
    this.messageCallbacks.delete(callback);
  }

  /**
   * Register callback for status changes
   */
  public onStatus(callback: StatusCallback): void {
    this.statusCallbacks.add(callback);
  }

  /**
   * Unregister status callback
   */
  public offStatus(callback: StatusCallback): void {
    this.statusCallbacks.delete(callback);
  }

  /**
   * Get current connection status
   */
  public getStatus(): WsStatus {
    return this.status;
  }

  /**
   * Check if connected
   */
  public isConnected(): boolean {
    return this.status === "connected";
  }

  /**
   * Private helper methods
   */

  private setStatus(newStatus: WsStatus): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusCallbacks.forEach((callback) => callback(newStatus));
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: "ping" });
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(
        `[WS] Max reconnection attempts (${this.maxReconnectAttempts}) reached`
      );
      return;
    }

    this.reconnectAttempts++;
    console.log(
      `[WS] Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${this.reconnectDelay}ms`
    );

    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (capped)
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 2,
      this.maxReconnectDelay
    );
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

/**
 * Singleton WebSocket client instance
 */
let wsInstance: WebSocketClient | null = null;

export function createWebSocketClient(config: WsConfig): WebSocketClient {
  if (!wsInstance) {
    wsInstance = new WebSocketClient(config);
  }
  return wsInstance;
}

export function getWebSocketClient(): WebSocketClient | null {
  return wsInstance;
}

export function closeWebSocketClient(): void {
  if (wsInstance) {
    wsInstance.disconnect();
    wsInstance = null;
  }
}
