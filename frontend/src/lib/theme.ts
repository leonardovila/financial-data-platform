// ──────────────────────────────────────────────────────────────────────────────
// FRONT-002: Lightweight Charts colorspace — maps to index.css palette.
// Import this in Chart.tsx to keep the chart visually coherent with the UI.
// ──────────────────────────────────────────────────────────────────────────────

import type { DeepPartial, ChartOptions, CandlestickStyleOptions, HistogramStyleOptions } from "lightweight-charts";

export const colors = {
  bg: "#0a0a0a",
  panel: "#111111",
  hover: "#1a1a1a",
  border: "#222222",
  text: "#e0e0e0",
  muted: "#666666",
  neon: "#00ff00",
  red: "#ff0044",
  blue: "#0088ff",
  yellow: "#ffcc00",
} as const;

export const chartOptions: DeepPartial<ChartOptions> = {
  layout: {
    background: { color: colors.bg },
    textColor: colors.muted,
    fontFamily:
      '"JetBrains Mono", "Roboto Mono", "Fira Code", ui-monospace, monospace',
    fontSize: 11,
  },
  grid: {
    vertLines: { color: colors.border },
    horzLines: { color: colors.border },
  },
  crosshair: {
    vertLine: { color: colors.muted, width: 1, style: 2, labelBackgroundColor: colors.panel },
    horzLine: { color: colors.muted, width: 1, style: 2, labelBackgroundColor: colors.panel },
  },
  rightPriceScale: {
    borderColor: colors.border,
  },
  timeScale: {
    borderColor: colors.border,
    timeVisible: false,
    secondsVisible: false,
  },
};

export const candlestickStyles: DeepPartial<CandlestickStyleOptions> = {
  upColor: colors.neon,
  downColor: colors.red,
  borderUpColor: colors.neon,
  borderDownColor: colors.red,
  wickUpColor: colors.neon,
  wickDownColor: colors.red,
};

export const volumeUpColor = "rgba(0, 255, 0, 0.12)";
export const volumeDownColor = "rgba(255, 0, 68, 0.12)";

export const volumeStyles: DeepPartial<HistogramStyleOptions> = {
  color: volumeUpColor,
};
