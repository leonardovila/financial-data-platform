// ──────────────────────────────────────────────────────────────────────────────
// FRONT-004: Main Candlestick Chart (Lightweight Charts v5)
//
// - Created ONCE on mount. Never destroyed on symbol switch.
// - Seed → series.setData(). Tick → series.update() (O(1)).
// - ResizeObserver handles all viewport changes (orientation, split-view, resize).
// - Touch-native: pinch-to-zoom, pan. Crosshair tooltip disabled on mobile.
// ──────────────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type UTCTimestamp,
} from "lightweight-charts";
import { useWsStore } from "../stores/wsStore";
import {
  chartOptions,
  candlestickStyles,
  volumeStyles,
  volumeUpColor,
  volumeDownColor,
} from "../lib/theme";
import type { SeedCandle, CandleDict } from "../types/ws";

// ── Format converters ──

function seedToCandle(c: SeedCandle): CandlestickData {
  return {
    time: c[0] as UTCTimestamp,
    open: c[1],
    high: c[2],
    low: c[3],
    close: c[4],
  };
}

function seedToVolume(c: SeedCandle): HistogramData {
  return {
    time: c[0] as UTCTimestamp,
    value: c[5] ?? 0,
    color: c[4] >= c[1] ? volumeUpColor : volumeDownColor,
  };
}

function tickToCandle(c: CandleDict): CandlestickData {
  return {
    time: c.ts as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  };
}

function tickToVolume(c: CandleDict): HistogramData {
  return {
    time: c.ts as UTCTimestamp,
    value: c.volume,
    color: c.close >= c.open ? volumeUpColor : volumeDownColor,
  };
}

// ── Mobile detection ──
const IS_TOUCH =
  typeof navigator !== "undefined" && navigator.maxTouchPoints > 0;

export default function Chart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // ── Create chart ONCE on mount ──
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      ...chartOptions,
      autoSize: true, // LWC handles ResizeObserver internally — no manual width/height
      crosshair: {
        ...chartOptions.crosshair,
        ...(IS_TOUCH ? { horzLine: { ...chartOptions.crosshair?.horzLine, labelVisible: false } } : {}),
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, candlestickStyles);
    const volumeSeries = chart.addSeries(HistogramSeries, {
      ...volumeStyles,
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // ── Data Subscriptions (Seed & Tick) ──
  useEffect(() => {
    const unsub = useWsStore.subscribe((state, prevState) => {
      
      // 1. Handle Seed Data (cuando cambiamos de símbolo o carga inicial)
      if (state.seedData && state.seedData !== prevState.seedData) {
        if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

        const raw = state.seedData.chart_candles;
        if (raw.length === 0) return;

        // Sanitize: deduplicate by ts (keep last), sort ascending
        const dedupMap = new Map<number, SeedCandle>();
        for (const c of raw) {
          dedupMap.set(c[0], c); 
        }
        const clean = Array.from(dedupMap.values()).sort((a, b) => a[0] - b[0]);

        candleSeriesRef.current.setData(clean.map(seedToCandle));
        volumeSeriesRef.current.setData(clean.map(seedToVolume));

        // Reset BOTH axes to fit the new symbol's data range
        chartRef.current?.timeScale().fitContent();              // horizontal
        chartRef.current?.priceScale("right").applyOptions({});  // force Y-axis recalc
        chartRef.current?.priceScale("volume").applyOptions({    // force volume recalc
          scaleMargins: { top: 0.85, bottom: 0 },
        });
      }

      // 2. Handle Transient Tick (cuando llega un nuevo precio en vivo)
      if (state.latestTick && state.latestTick !== prevState.latestTick) {
        if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

        candleSeriesRef.current.update(tickToCandle(state.latestTick.candle));
        volumeSeriesRef.current.update(tickToVolume(state.latestTick.candle));
      }
    });

    return unsub; // Limpieza al desmontar
  }, []);

  return (
    <div
      ref={containerRef}
      className="w-full h-full min-h-[200px]"
    />
  );
}
