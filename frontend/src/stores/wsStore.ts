// ──────────────────────────────────────────────────────────────────────────────
// FRONT-003: WebSocket Client Manager (Zustand)
//
// Owns the entire WS lifecycle: connect, disconnect, reconnect, symbol switch.
// Parses incoming messages and distributes to typed slices.
// Mobile-aware: visibility API pause, reduced tick history on touch devices.
// ──────────────────────────────────────────────────────────────────────────────

import { create } from "zustand";
import type {
  SeedPayload,
  TickPayload,
  FundamentalsData,
  AllMetrics,
  WsMessage,
} from "../types/ws";

// ── Mobile detection (run once at module load) ──
const IS_TOUCH =
  typeof navigator !== "undefined" && navigator.maxTouchPoints > 0;
const TICK_HISTORY_CAP = IS_TOUCH ? 20 : 50;

// ── Reconnection config ──
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 16000;

// ── WS host: defaults to same host as the page, ws:// or wss:// ──
const WS_BASE =
  import.meta.env.VITE_WS_URL ??
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

// ──────────────────────────────────────────────────────────────────────────────
// Store types
// ──────────────────────────────────────────────────────────────────────────────

type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

interface WsState {
  // Connection
  socket: WebSocket | null;
  status: ConnectionStatus;
  connectionError: string | null;

  // Symbol
  currentSymbol: string;
  companyName: string | null;

  // Data
  seedData: SeedPayload | null;
  latestTick: TickPayload | null;
  tickHistory: TickPayload[];
  fundamentals: FundamentalsData | null;
  metrics: AllMetrics;

  // Derived
  isMarketOpen: boolean;

  // Actions
  connect: (symbol: string) => void;
  disconnect: () => void;
  switchSymbol: (newSymbol: string) => void;
}

// ── Module-level refs (outside Zustand for zero-cost access) ──
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let visibilityHandler: (() => void) | null = null;
let pendingReconnectSymbol: string | null = null;

// ──────────────────────────────────────────────────────────────────────────────
// Store
// ──────────────────────────────────────────────────────────────────────────────

export const useWsStore = create<WsState>()((set, get) => {
  // ── Internal: clear reconnect state ──
  function clearReconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    reconnectAttempt = 0;
    pendingReconnectSymbol = null;
  }

  // ── Internal: schedule reconnection with exponential backoff ──
  function scheduleReconnect(symbol: string) {
    // Don't reconnect if page is hidden (mobile battery saver)
    if (document.visibilityState === "hidden") {
      pendingReconnectSymbol = symbol;
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** reconnectAttempt,
      RECONNECT_MAX_MS
    );
    reconnectAttempt++;

    set({ status: "reconnecting" });

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      get().connect(symbol);
    }, delay);
  }

  // ── Internal: install visibility listener (once) ──
  function ensureVisibilityListener() {
    if (visibilityHandler) return;

    visibilityHandler = () => {
      if (
        document.visibilityState === "visible" &&
        pendingReconnectSymbol
      ) {
        const sym = pendingReconnectSymbol;
        pendingReconnectSymbol = null;
        scheduleReconnect(sym);
      }
    };

    document.addEventListener("visibilitychange", visibilityHandler);
  }

  // ── Internal: message dispatcher ──
  function handleMessage(raw: string) {
    let msg: WsMessage;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    switch (msg.type) {
      case "seed":
        set({
          seedData: msg,
          companyName: msg.company_name,
          fundamentals: msg.fundamentals,
          metrics: msg.metrics,
          isMarketOpen: true,
        });
        break;

      case "tick": {
        // ── TRANSITION LOCK: drop rogue ticks until fresh seed arrives ──
        // switchSymbol() sets seedData=null. Any tick arriving before the
        // new seed is a stale message from the old symbol's chart session.
        if (!get().seedData) return;

        const prev = get().tickHistory;
        const history = [msg, ...prev].slice(0, TICK_HISTORY_CAP);
        set({
          latestTick: msg,
          tickHistory: history,
          metrics: msg.metrics,
          isMarketOpen: true,
        });
        break;
      }

      case "company_name":
        set({ companyName: msg.name });
        break;

      case "fundamentals":
        set({ fundamentals: msg.data });
        break;

      case "heartbeat":
        set({ isMarketOpen: false });
        break;

      case "error":
        set({ connectionError: msg.message });
        break;

      case "session_expired":
        // Immediate reconnect — server closed us on TTL
        get().disconnect();
        reconnectAttempt = 0; // reset backoff for clean reconnect
        scheduleReconnect(get().currentSymbol);
        break;

      case "idle_warning":
        // Could surface to UI — for now just send a ping to keep alive
        get().socket?.send(JSON.stringify({ action: "ping" }));
        break;

      case "idle_disconnect":
        get().disconnect();
        // Only reconnect if user is actively looking
        if (document.visibilityState === "visible") {
          reconnectAttempt = 0;
          scheduleReconnect(get().currentSymbol);
        } else {
          pendingReconnectSymbol = get().currentSymbol;
        }
        break;

      case "pong":
        // No-op — keepalive acknowledged
        break;
    }
  }

  return {
    // ── Initial state ──
    socket: null,
    status: "disconnected",
    connectionError: null,
    currentSymbol: "",
    companyName: null,
    seedData: null,
    latestTick: null,
    tickHistory: [],
    fundamentals: null,
    metrics: { performance: null, volatility: null, volume: null },
    isMarketOpen: false,

    // ── connect ──
    connect(symbol: string) {
      // Clean up any existing socket
      const prev = get().socket;
      if (prev) {
        prev.onclose = null; // prevent reconnect trigger
        prev.close();
      }
      clearReconnect();
      ensureVisibilityListener();

      const sym = symbol.toUpperCase();
      set({
        status: "connecting",
        currentSymbol: sym,
        connectionError: null,
        seedData: null,
        latestTick: null,
        tickHistory: [],
        companyName: null,
        fundamentals: null,
        metrics: { performance: null, volatility: null, volume: null },
        isMarketOpen: false,
      });

      const ws = new WebSocket(`${WS_BASE}/ws/live/${sym}`);

      ws.onopen = () => {
        reconnectAttempt = 0; // reset backoff on successful connect
        set({ socket: ws, status: "connected", connectionError: null });
      };

      ws.onmessage = (event) => {
        handleMessage(event.data);
      };

      ws.onclose = (event) => {
        set({ socket: null });

        // Code 1000 = normal close (we called disconnect())
        // Code 4003/4001/4029 = security/capacity rejection — don't retry
        if (event.code === 1000) {
          set({ status: "disconnected" });
          return;
        }
        if (event.code === 4003 || event.code === 4001 || event.code === 4029) {
          set({
            status: "disconnected",
            connectionError: event.reason || `Rejected (${event.code})`,
          });
          return;
        }

        // Unexpected close — reconnect
        scheduleReconnect(sym);
      };

      ws.onerror = () => {
        // onerror is always followed by onclose — handle there
        set({ connectionError: "Connection error" });
      };

      set({ socket: ws });
    },

    // ── disconnect ──
    disconnect() {
      clearReconnect();
      const ws = get().socket;
      if (ws) {
        ws.onclose = null; // prevent reconnect trigger
        ws.close(1000);
      }
      set({
        socket: null,
        status: "disconnected",
      });
    },

    // ── switchSymbol ──
    switchSymbol(newSymbol: string) {
      const ws = get().socket;
      const sym = newSymbol.toUpperCase();

      if (!ws || ws.readyState !== WebSocket.OPEN) {
        // No active connection — do a fresh connect
        get().connect(sym);
        return;
      }

      // Reset display state for the new symbol
      set({
        currentSymbol: sym,
        seedData: null,
        latestTick: null,
        tickHistory: [],
        companyName: null,
        fundamentals: null,
        metrics: { performance: null, volatility: null, volume: null },
        isMarketOpen: false,
        connectionError: null,
      });

      // Send switch command over the existing socket
      ws.send(JSON.stringify({ action: "switch", symbol: sym }));
    },
  };
});
