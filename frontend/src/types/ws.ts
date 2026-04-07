// ──────────────────────────────────────────────────────────────────────────────
// FRONT-001: WebSocket payload types — the contract with the Python backend.
// Discriminated union on "type" field enables exhaustive switch/case narrowing.
// ──────────────────────────────────────────────────────────────────────────────

// ── Candle formats ──

/** Raw candle from seed: [ts, open, high, low, close, volume] */
export type SeedCandle = [number, number, number, number, number, number];

/** Parsed candle dict from tick payloads */
export interface CandleDict {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Metric payloads ──

export interface PerformanceMetrics {
  ret_1d: number | null;
  ret_1w: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  ret_6m: number | null;
  ret_1y: number | null;
}

export interface VolatilityMetrics {
  range_intraday: number | null;
  vol_1w: number | null;
  vol_1m: number | null;
  vol_3m: number | null;
  vol_6m: number | null;
  vol_1y: number | null;
}

export interface MomentumMetrics {
  rsi_14: number | null;
  sma_20_gap: number | null;
  sma_50_gap: number | null;
  sma_200_gap: number | null;
  high_dist_1m: number | null;
  high_dist_1y: number | null;
}

export interface AllMetrics {
  performance: PerformanceMetrics | null;
  volatility: VolatilityMetrics | null;
  momentum: MomentumMetrics | null;
}

// ── Fundamentals ──

export interface FundamentalsData {
  symbol: string;
  as_of_ts: number;
  company_name: string | null;
  market_cap: number | null;
  pe_ttm: number | null;
  eps_ttm: number | null;
  shares_outstanding: number | null;
  sector: string | null;
  industry: string | null;
}

// ── Server → Client messages (discriminated union on "type") ──

export interface SeedPayload {
  type: "seed";
  symbol: string;
  chart_candles: SeedCandle[];
  company_name: string | null;
  fundamentals: FundamentalsData | null;
  metrics: AllMetrics;
}

export interface TickPayload {
  type: "tick";
  candle: CandleDict;
  metrics: AllMetrics;
  ts: number;
}

export interface CompanyNamePayload {
  type: "company_name";
  name: string;
}

export interface FundamentalsPayload {
  type: "fundamentals";
  data: FundamentalsData;
}

export interface HeartbeatPayload {
  type: "heartbeat";
}

export interface ErrorPayload {
  type: "error";
  message: string;
}

export interface SessionExpiredPayload {
  type: "session_expired";
}

export interface IdleWarningPayload {
  type: "idle_warning";
}

export interface IdleDisconnectPayload {
  type: "idle_disconnect";
}

export interface PongPayload {
  type: "pong";
}

export type WsMessage =
  | SeedPayload
  | TickPayload
  | CompanyNamePayload
  | FundamentalsPayload
  | HeartbeatPayload
  | ErrorPayload
  | SessionExpiredPayload
  | IdleWarningPayload
  | IdleDisconnectPayload
  | PongPayload;

// ── Client → Server commands ──

export interface SwitchCommand {
  action: "switch";
  symbol: string;
}

export interface PingCommand {
  action: "ping";
}

export type WsCommand = SwitchCommand | PingCommand;
