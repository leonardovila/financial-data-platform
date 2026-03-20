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
      width: el.clientWidth,
      height: el.clientHeight,
      crosshair: {
        ...chartOptions.crosshair,
        // Disable crosshair tooltip on mobile — it covers the candles
        ...(IS_TOUCH ? { horzLine: { ...chartOptions.crosshair?.horzLine, labelVisible: false } } : {}),
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, candlestickStyles);
    const volumeSeries = chart.addSeries(HistogramSeries, {
      ...volumeStyles,
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
    });

    // Volume overlay: scale to bottom 15% of chart
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // ── ResizeObserver: handles all viewport changes ──
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          chart.resize(width, height);
        }
      }
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // ── Seed: full data replacement on new symbol ──
  useEffect(() => {
    return useWsStore.subscribe(
      (state) => state.seedData,
      (seedData) => {
        if (!seedData || !candleSeriesRef.current || !volumeSeriesRef.current)
          return;

        const candles = seedData.chart_candles;
        if (candles.length === 0) return;

        candleSeriesRef.current.setData(candles.map(seedToCandle));
        volumeSeriesRef.current.setData(candles.map(seedToVolume));

        // Fit content to show all candles, then scroll to the latest
        chartRef.current?.timeScale().fitContent();
      }
    );
  }, []);

  // ── Tick: O(1) bar update ──
  useEffect(() => {
    return useWsStore.subscribe(
      (state) => state.latestTick,
      (tick) => {
        if (!tick || !candleSeriesRef.current || !volumeSeriesRef.current)
          return;

        candleSeriesRef.current.update(tickToCandle(tick.candle));
        volumeSeriesRef.current.update(tickToVolume(tick.candle));
      }
    );
  }, []);

  return (
    <div
      ref={containerRef}
      className="w-full h-full min-h-0"
      style={{ contain: "strict" }}
    />
  );
}
