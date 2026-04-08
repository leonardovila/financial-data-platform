// ──────────────────────────────────────────────────────────────────────────────
// FRONT-005: TickStack — brutalist live order-flow feed
//
// Desktop: persistent right sidebar, 50 rows, 3 columns (time, price, delta).
// Mobile:  hidden by default. Floating "FEED" pill → bottom-sheet overlay.
//          20 rows, 3 columns (time, price, delta). h-9 touch rows.
//
// GPU-accelerated: will-change:transform, slideIn animation on new ticks.
// React.memo on each row — only the newest row renders.
// ──────────────────────────────────────────────────────────────────────────────

import { memo } from "react";
import { useWsStore } from "../stores/wsStore";
import { formatCurrency, formatTimestamp, signClass } from "../lib/formatters";
import type { TickPayload } from "../types/ws";
import InfoTooltip from "./InfoTooltip";
import { LIVE_FEED_GLOSSARY } from "../lib/glossary";

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
        "flex items-center gap-4 px-2 font-mono text-xs sm:text-sm",
        // Desktop: h-7 dense. Mobile: h-9 touch-friendly.
        "h-9 sm:h-7",
        // Alternating bg — odd rows get panel bg
        "odd:bg-[var(--color-panel)]",
        // slideIn animation only on the newest row
        isFirst ? "animate-[slideIn_150ms_ease-out]" : "",
      ].join(" ")}
    >
      {/* Time — w-[68px] holds "12:03:45" in font-mono without truncating */}
      <span className="shrink-0 w-[68px] text-[var(--color-muted)] tabular-nums">
        {formatTimestamp(tick.ts)}
      </span>

      {/* Price — content-sized, sits right next to Time with gap-4 */}
      <span className="shrink-0 truncate text-[var(--color-text)] tabular-nums">
        {formatCurrency(candle.close)}
      </span>

      {/* Delta — sits right next to Price (no ml-auto), trailing space goes to the right */}
      <span className={`shrink-0 w-16 text-right tabular-nums ${delta !== null ? signClass(delta) : "text-[var(--color-muted)]"}`}>
        {delta !== null
          ? `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`
          : "—"}
      </span>
    </div>
  );
});

// ── Tick list renderer (shared between desktop sidebar and mobile sheet) ──

function TickList({ maxRows = 20 }: { maxRows?: number } = {}) {
  const tickHistory = useWsStore((s) => s.tickHistory);

  // Hachazo directo. Nada de scroll, nada de renderizar 50 filas invisibles.
  const displayTicks = tickHistory.slice(0, maxRows);

  if (displayTicks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[var(--color-muted)]">
        Waiting for ticks...
      </div>
    );
  }

  return (
    // Agregamos el border-b acá para la raya final que pediste
    <div className="overflow-hidden will-change-transform border-b border-[var(--color-border)]">
      {displayTicks.map((tick, i) => (
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
    <div className="flex items-center gap-4 px-2 h-7 text-[10px] uppercase tracking-widest text-[var(--color-muted)] border-b border-[var(--color-border)]">
      <span className="shrink-0 w-[68px]">Time</span>
      <span className="shrink-0">Price</span>
      <span className="shrink-0 w-16 text-right">Delta</span>
    </div>
  );
}

// ── Desktop sidebar (sm+ — always visible, rendered by Dashboard grid) ──
export function TickStackSidebar() {
  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)] border-l border-[var(--color-border)]">
      {/* Header agresivo en neón con pulso para gritar LIVE en desktop */}
      <div className="px-2 py-1 text-[10px] text-[var(--color-neon)] font-bold uppercase tracking-widest border-b border-[var(--color-border)] flex items-center gap-2 bg-[var(--color-panel)]">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-neon)] pulse" />
        <span>LIVE PRICE FEED</span>
        {/* Forzamos normal-case y limpiamos el espaciado y la negrita heredada */}
        <div className="ml-auto normal-case tracking-normal font-normal text-left text-[var(--color-text)]">
          <InfoTooltip text={LIVE_FEED_GLOSSARY.description} size="sm" />
        </div>
      </div>
      <TickHeader />
      
      {/* Flex child clipped:
          - flex-1: ocupa el espacio restante del sidebar (después del header + TickHeader)
          - min-h-0: anula el min-height:auto default del flex item, permite encoger por debajo del contenido
          - overflow-hidden: las filas que no entran se recortan (hachazo, sin scroll) */}
      <div className="flex-1 min-h-0 overflow-hidden bg-[var(--color-bg)]">
        <TickList maxRows={20} />
      </div>
    </div>
  );
}

// ── Mobile bottom-sheet (< sm — toggle via pill button) ──

// ── Mobile embedded feed (< sm) ──
// Ocupa espacio real en el DOM, robándole altura al Chart.

export function TickStackMobile() {
  const tickHistory = useWsStore((s) => s.tickHistory);
  
  // Cortamos a 4 ticks máximo. Densidad total.
  const displayTicks = tickHistory.slice(0, 4);

  return (
    <div className="sm:hidden flex flex-col shrink-0 w-full bg-[var(--color-bg)] border-t border-[var(--color-border)]">
      {/* Indicador de estado LIVE */}
      <div className="px-2 py-1 text-[9px] text-[var(--color-neon)] font-bold uppercase tracking-widest border-b border-[var(--color-border)] flex items-center gap-2 bg-[var(--color-panel)]">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-neon)] pulse" />
        <span>LIVE PRICE FEED</span>
        {/* Forzamos normal-case y limpiamos el espaciado y la negrita heredada */}
        <div className="ml-auto normal-case tracking-normal font-normal text-left text-[var(--color-text)]">
          <InfoTooltip text={LIVE_FEED_GLOSSARY.description} size="sm" />
        </div>
      </div>
      
      <TickHeader />
      
      <div className="flex flex-col overflow-hidden">
        {displayTicks.length === 0 ? (
          <div className="flex items-center justify-center h-12 text-xs text-[var(--color-muted)]">
            Waiting for ticks...
          </div>
        ) : (
          displayTicks.map((tick, i) => (
            <TickRow
              key={tick.ts + "-" + tick.candle.ts}
              tick={tick}
              prevClose={
                i + 1 < tickHistory.length ? tickHistory[i + 1].candle.close : null
              }
              isFirst={i === 0}
            />
          ))
        )}
      </div>
    </div>
  );
}
