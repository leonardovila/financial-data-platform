// ──────────────────────────────────────────────────────────────────────────────
// FRONT-005: TickStack — brutalist live order-flow feed
//
// Desktop: persistent right sidebar, 50 rows, 4 columns (time, price, delta, vol).
// Mobile:  hidden by default. Floating "FEED" pill → bottom-sheet overlay.
//          20 rows, 3 columns (time, price, delta). h-9 touch rows.
//
// GPU-accelerated: will-change:transform, slideIn animation on new ticks.
// React.memo on each row — only the newest row renders.
// ──────────────────────────────────────────────────────────────────────────────

import { memo, useState } from "react";
import { useWsStore } from "../stores/wsStore";
import { formatCurrency, formatTimestamp, signClass } from "../lib/formatters";
import type { TickPayload } from "../types/ws";

// ── Single tick row (memoized — only new rows render) ──

interface TickRowProps {
  tick: TickPayload;
  prevClose: number | null;
  isFirst: boolean;
}

const TickRow = memo(function TickRow({ tick, prevClose, isFirst }: TickRowProps) {
  const { candle } = tick;
  const delta = prevClose !== null ? candle.close - prevClose : null;

  return (
    <div
      className={[
        "flex items-center gap-1 px-2 font-mono text-xs",
        // Desktop: h-7 dense. Mobile: h-9 touch-friendly.
        "h-9 sm:h-7",
        // Alternating bg — odd rows get panel bg
        "odd:bg-[var(--color-panel)]",
        // slideIn animation only on the newest row
        isFirst ? "animate-[slideIn_150ms_ease-out]" : "",
      ].join(" ")}
    >
      {/* Time */}
      <span className="shrink-0 w-16 text-[var(--color-muted)]">
        {formatTimestamp(tick.ts)}
      </span>

      {/* Price */}
      <span className="flex-1 min-w-0 truncate text-right text-[var(--color-text)]">
        {formatCurrency(candle.close)}
      </span>

      {/* Delta */}
      <span className={`shrink-0 w-18 text-right ${delta !== null ? signClass(delta) : "text-[var(--color-muted)]"}`}>
        {delta !== null
          ? `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`
          : "—"}
      </span>

      {/* Volume — hidden on mobile, visible on sm+ */}
      <span className="hidden sm:block shrink-0 w-20 text-right text-[var(--color-muted)]">
        {formatCurrency(candle.volume, 0)}
      </span>
    </div>
  );
});

// ── Tick list renderer (shared between desktop sidebar and mobile sheet) ──

function TickList() {
  const tickHistory = useWsStore((s) => s.tickHistory);

  if (tickHistory.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[var(--color-muted)]">
        Waiting for ticks...
      </div>
    );
  }

  return (
    <div className="overflow-hidden will-change-transform">
      {tickHistory.map((tick, i) => (
        <TickRow
          key={tick.ts + "-" + tick.candle.ts}
          tick={tick}
          prevClose={
            i + 1 < tickHistory.length
              ? tickHistory[i + 1].candle.close
              : null
          }
          isFirst={i === 0}
        />
      ))}
    </div>
  );
}

// ── Column headers ──

function TickHeader() {
  return (
    <div className="flex items-center gap-1 px-2 h-6 text-[10px] uppercase tracking-widest text-[var(--color-muted)] border-b border-[var(--color-border)]">
      <span className="shrink-0 w-16">Time</span>
      <span className="flex-1 min-w-0 text-right">Price</span>
      <span className="shrink-0 w-18 text-right">Delta</span>
      <span className="hidden sm:block shrink-0 w-20 text-right">Volume</span>
    </div>
  );
}

// ── Desktop sidebar (sm+ — always visible, rendered by Dashboard grid) ──

export function TickStackSidebar() {
  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)] border-l border-[var(--color-border)]">
      <div className="px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--color-muted)] border-b border-[var(--color-border)]">
        Live Feed
      </div>
      <TickHeader />
      <div className="flex-1 min-h-0 overflow-hidden">
        <TickList />
      </div>
    </div>
  );
}

// ── Mobile bottom-sheet (< sm — toggle via pill button) ──

export function TickStackMobile() {
  const [open, setOpen] = useState(false);
  const tickCount = useWsStore((s) => s.tickHistory.length);

  return (
    <>
      {/* Feed pill — pinned inside Nginx navbar, top-right on mobile */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={[
          "fixed top-[7px] right-3 sm:hidden",
          "flex items-center gap-1.5 px-2.5 py-1",
          "text-[10px] uppercase tracking-widest font-mono rounded",
          "border transition-colors duration-150",
          open
            ? "bg-[var(--color-neon)] text-[var(--color-bg)] border-[var(--color-neon)]"
            : "bg-[var(--color-panel)] text-[var(--color-muted)] border-[var(--color-border)]",
        ].join(" ")}
        style={{ zIndex: 100000 }}
        aria-label={open ? "Close live feed" : "Open live feed"}
      >
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full ${
            tickCount > 0 ? "bg-[var(--color-neon)] pulse" : "bg-[var(--color-muted)]"
          }`}
        />
        Feed
      </button>

      {/* Bottom sheet overlay */}
      <div
        className={[
          "fixed inset-x-0 bottom-0 z-40 sm:hidden",
          "bg-[var(--color-bg)] border-t border-[var(--color-border)]",
          "transition-transform duration-200 ease-out",
          open ? "translate-y-0" : "translate-y-full",
        ].join(" ")}
        style={{ height: "50dvh" }}
      >
        {/* Drag handle */}
        <div className="flex justify-center py-2">
          <div className="w-10 h-1 rounded-full bg-[var(--color-border)]" />
        </div>

        <TickHeader />

        <div className="flex-1 overflow-hidden" style={{ height: "calc(50dvh - 52px)" }}>
          <TickList />
        </div>
      </div>

      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/40 sm:hidden"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  );
}
