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
import { useI18n } from "../i18n";

export default function MetricsGrid() {
  const { t } = useI18n();
  const metrics = useWsStore((s) => s.metrics);

  const TABS = [t("metrics.performance"), t("metrics.volatility"), t("metrics.momentum")] as const;

  // ── Build row configs from live metrics ──

  const perfRows = [
    { label: t("perf.1d"), value: metrics.performance?.ret_1d, format: formatPercent, help: t("glossary.perf.ret_1d") },
    { label: t("perf.1w"), value: metrics.performance?.ret_1w, format: formatPercent, help: t("glossary.perf.ret_1w") },
    { label: t("perf.1m"), value: metrics.performance?.ret_1m, format: formatPercent, help: t("glossary.perf.ret_1m") },
    { label: t("perf.3m"), value: metrics.performance?.ret_3m, format: formatPercent, help: t("glossary.perf.ret_3m") },
    { label: t("perf.6m"), value: metrics.performance?.ret_6m, format: formatPercent, help: t("glossary.perf.ret_6m") },
    { label: t("perf.1y"), value: metrics.performance?.ret_1y, format: formatPercent, help: t("glossary.perf.ret_1y") },
  ];

  const volRows = [
    { label: t("vol.range"), value: metrics.volatility?.range_intraday, format: formatPercent, colored: false, help: t("glossary.vol.range") },
    { label: t("vol.1w"), value: metrics.volatility?.vol_1w, format: formatPercent, colored: false, help: t("glossary.vol.1w") },
    { label: t("vol.1m"), value: metrics.volatility?.vol_1m, format: formatPercent, colored: false, help: t("glossary.vol.1m") },
    { label: t("vol.3m"), value: metrics.volatility?.vol_3m, format: formatPercent, colored: false, help: t("glossary.vol.3m") },
    { label: t("vol.6m"), value: metrics.volatility?.vol_6m, format: formatPercent, colored: false, help: t("glossary.vol.6m") },
    { label: t("vol.1y"), value: metrics.volatility?.vol_1y, format: formatPercent, colored: false, help: t("glossary.vol.1y") },
  ];

  const momentumRows = [
    { label: t("mom.rsi"), value: metrics.momentum?.rsi_14, format: formatNumber, colored: false, help: t("glossary.mom.rsi_14") },
    { label: t("mom.sma20"), value: metrics.momentum?.sma_20_gap, format: formatPercent, help: t("glossary.mom.sma_20_gap") },
    { label: t("mom.sma50"), value: metrics.momentum?.sma_50_gap, format: formatPercent, help: t("glossary.mom.sma_50_gap") },
    { label: t("mom.sma200"), value: metrics.momentum?.sma_200_gap, format: formatPercent, help: t("glossary.mom.sma_200_gap") },
    { label: t("mom.high1m"), value: metrics.momentum?.high_dist_1m, format: formatPercent, help: t("glossary.mom.high_dist_1m") },
    { label: t("mom.high1y"), value: metrics.momentum?.high_dist_1y, format: formatPercent, help: t("glossary.mom.high_dist_1y") },
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
        <MetricCard title={t("metrics.performance")} rows={perfRows} categoryHelp={t("glossary.perf.category")} />
        <MetricCard title={t("metrics.volatility")} rows={volRows} categoryHelp={t("glossary.vol.category")} />
        <MetricCard title={t("metrics.momentum")} rows={momentumRows} categoryHelp={t("glossary.mom.category")} />
      </div>
    </div>
  );
}
