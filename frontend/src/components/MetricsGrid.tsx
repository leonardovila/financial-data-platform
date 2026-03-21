// ──────────────────────────────────────────────────────────────────────────────
// FRONT-006: MetricsGrid — Performance / Volatility / Volume
//
// Desktop (sm+): CSS grid-cols-3, all three cards visible simultaneously.
// Mobile (<sm):  Scroll-snap tabs. Tab bar at top (PERF | VOL | RISK).
//                One card visible at a time. Native iOS momentum swipe.
// ──────────────────────────────────────────────────────────────────────────────

import { useRef, useState, useEffect } from "react";
import { useWsStore } from "../stores/wsStore";
import MetricCard from "./MetricCard";
import { formatPercent, formatLargeNumber } from "../lib/formatters";

const TABS = ["PERF", "VOL", "RISK"] as const;

export default function MetricsGrid() {
  const metrics = useWsStore((s) => s.metrics);

  // ── Build row configs from live metrics ──

  const perfRows = [
    { label: "Ret 1D", value: metrics.performance?.ret_1d, format: formatPercent },
    { label: "Ret 1W", value: metrics.performance?.ret_1w, format: formatPercent },
    { label: "Ret 1M", value: metrics.performance?.ret_1m, format: formatPercent },
    { label: "Ret 3M", value: metrics.performance?.ret_3m, format: formatPercent },
    { label: "Ret 6M", value: metrics.performance?.ret_6m, format: formatPercent },
    { label: "Ret 1Y", value: metrics.performance?.ret_1y, format: formatPercent },
  ];

  const volRows = [
    { label: "Range", value: metrics.volatility?.range_intraday, format: formatPercent, colored: false },
    { label: "Vol 1W", value: metrics.volatility?.vol_1w, format: formatPercent, colored: false },
    { label: "Vol 1M", value: metrics.volatility?.vol_1m, format: formatPercent, colored: false },
    { label: "Vol 3M", value: metrics.volatility?.vol_3m, format: formatPercent, colored: false },
    { label: "Vol 6M", value: metrics.volatility?.vol_6m, format: formatPercent, colored: false },
    { label: "Vol 1Y", value: metrics.volatility?.vol_1y, format: formatPercent, colored: false },
  ];

  const volumeRows = [
    { label: "Vol USD", value: metrics.volume?.volume_usd, format: formatLargeNumber, colored: false },
    { label: "SMA 20", value: metrics.volume?.vol_sma_20, format: formatLargeNumber, colored: false },
    { label: "SMA 50", value: metrics.volume?.vol_sma_50, format: formatLargeNumber, colored: false },
    { label: "Gap 20", value: metrics.volume?.vol_gap_20, format: formatPercent },
    { label: "Gap 50", value: metrics.volume?.vol_gap_50, format: formatPercent },
    { label: "Gap 200", value: metrics.volume?.vol_gap_200, format: formatPercent },
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
        <MetricCard title="Performance" rows={perfRows} />
        <MetricCard title="Volatility" rows={volRows} />
        <MetricCard title="Volume" rows={volumeRows} />
      </div>
    </div>
  );
}
