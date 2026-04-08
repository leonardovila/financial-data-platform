// ──────────────────────────────────────────────────────────────────────────────
// FRONT-006: MetricsGrid — Performance / Volatility / Momentum
//
// Desktop (sm+): CSS grid-cols-3, all three cards visible simultaneously.
// Mobile (<sm):  Scroll-snap tabs. Tab bar at top (PERFORMANCE | VOLATILITY | MOMENTUM).
//                One card visible at a time. Native iOS momentum swipe.
// ──────────────────────────────────────────────────────────────────────────────

import { useRef, useState, useEffect } from "react";
import { useWsStore } from "../stores/wsStore";
import MetricCard from "./MetricCard";
import { formatPercent, formatNumber } from "../lib/formatters";
import {
  PERFORMANCE_GLOSSARY,
  VOLATILITY_GLOSSARY,
  MOMENTUM_GLOSSARY,
} from "../lib/glossary";

const TABS = ["PERFORMANCE", "VOLATILITY", "MOMENTUM"] as const;

export default function MetricsGrid() {
  const metrics = useWsStore((s) => s.metrics);

  // ── Build row configs from live metrics ──

  const perfRows = [
    { label: "Price Change 1D", value: metrics.performance?.ret_1d, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_1d },
    { label: "Price Change 1W", value: metrics.performance?.ret_1w, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_1w },
    { label: "Price Change 1M", value: metrics.performance?.ret_1m, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_1m },
    { label: "Price Change 3M", value: metrics.performance?.ret_3m, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_3m },
    { label: "Price Change 6M", value: metrics.performance?.ret_6m, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_6m },
    { label: "Price Change 1Y", value: metrics.performance?.ret_1y, format: formatPercent, help: PERFORMANCE_GLOSSARY.ret_1y },
  ];

  const volRows = [
    { label: "Range", value: metrics.volatility?.range_intraday, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.range_intraday },
    { label: "Volatility 1W", value: metrics.volatility?.vol_1w, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.vol_1w },
    { label: "Volatility 1M", value: metrics.volatility?.vol_1m, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.vol_1m },
    { label: "Volatility 3M", value: metrics.volatility?.vol_3m, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.vol_3m },
    { label: "Volatility 6M", value: metrics.volatility?.vol_6m, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.vol_6m },
    { label: "Volatility 1Y", value: metrics.volatility?.vol_1y, format: formatPercent, colored: false, help: VOLATILITY_GLOSSARY.vol_1y },
  ];

  const momentumRows = [
    { label: "RSI 14", value: metrics.momentum?.rsi_14, format: formatNumber, colored: false, help: MOMENTUM_GLOSSARY.rsi_14 },
    { label: "SMA 20 Gap", value: metrics.momentum?.sma_20_gap, format: formatPercent, help: MOMENTUM_GLOSSARY.sma_20_gap },
    { label: "SMA 50 Gap", value: metrics.momentum?.sma_50_gap, format: formatPercent, help: MOMENTUM_GLOSSARY.sma_50_gap },
    { label: "SMA 200 Gap", value: metrics.momentum?.sma_200_gap, format: formatPercent, help: MOMENTUM_GLOSSARY.sma_200_gap },
    { label: "Off 1M High", value: metrics.momentum?.high_dist_1m, format: formatPercent, help: MOMENTUM_GLOSSARY.high_dist_1m },
    { label: "Off 52W High", value: metrics.momentum?.high_dist_1y, format: formatPercent, help: MOMENTUM_GLOSSARY.high_dist_1y },
  ];

  // ── Mobile tab state (synced with scroll-snap position) ──
  const [activeTab, setActiveTab] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Sync tab highlight to scroll position via IntersectionObserver
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const cards = container.children;
    if (cards.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = Array.from(cards).indexOf(entry.target as HTMLElement);
            if (idx >= 0) setActiveTab(idx);
          }
        }
      },
      { root: container, threshold: 0.6 }
    );

    Array.from(cards).forEach((card) => observer.observe(card));
    return () => observer.disconnect();
  }, []);

  // Tap a tab → scroll to that card
  function scrollToTab(idx: number) {
    const container = scrollRef.current;
    if (!container) return;
    const card = container.children[idx] as HTMLElement | undefined;
    card?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
  }

  return (
    <div className="border-t border-[var(--color-border)]">
      {/* ── Mobile tab bar (< sm) ── */}
      <div className="flex sm:hidden border-b border-[var(--color-border)]">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => scrollToTab(i)}
            className={[
              "flex-1 py-2 text-[10px] uppercase tracking-widest font-mono text-center transition-colors",
              activeTab === i
                ? "text-[var(--color-neon)] border-b-2 border-[var(--color-neon)]"
                : "text-[var(--color-muted)] border-b-2 border-transparent",
            ].join(" ")}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Cards container ──
           Mobile: horizontal scroll-snap (1 card visible at a time)
           Desktop: CSS grid-cols-3 (all visible) */}
      <div
        ref={scrollRef}
        className={[
          // Mobile: scroll-snap, constrain width to viewport
          "flex overflow-x-auto snap-x snap-mandatory w-full",
          // Desktop: grid
          "sm:grid sm:grid-cols-3 sm:overflow-visible",
        ].join(" ")}
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        <MetricCard title="Performance" rows={perfRows} categoryHelp={PERFORMANCE_GLOSSARY.category} />
        <MetricCard title="Volatility" rows={volRows} categoryHelp={VOLATILITY_GLOSSARY.category} />
        <MetricCard title="Momentum" rows={momentumRows} categoryHelp={MOMENTUM_GLOSSARY.category} />
      </div>
    </div>
  );
}
