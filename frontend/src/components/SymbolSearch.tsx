// ──────────────────────────────────────────────────────────────────────────────
// FRONT-008: SymbolSearch — persistent inline header bar
//
// Idle:   [🔍 BTC   Bitcoin   $67,432.10 ▲+1.23%]
// Active: [Search symbol...________________________] + dropdown overlay
//
// Zero modals. Zero Ctrl+K. Zero cognitive load.
// The bar IS the identity display AND the navigation input.
// ──────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect, useCallback } from "react";
import { useWsStore } from "../stores/wsStore";
import { formatCurrency, signClass } from "../lib/formatters";

const API_BASE =
  import.meta.env.VITE_API_URL ?? `${window.location.origin}`;

export default function SymbolSearch() {
  const currentSymbol = useWsStore((s) => s.currentSymbol);
  const companyName = useWsStore((s) => s.companyName);
  const latestTick = useWsStore((s) => s.latestTick);
  const seedData = useWsStore((s) => s.seedData);
  const switchSymbol = useWsStore((s) => s.switchSymbol);

  const [active, setActive] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [symbols, setSymbols] = useState<string[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Fetch symbol list once on mount ──
  useEffect(() => {
    fetch(`${API_BASE}/symbols`)
      .then((r) => r.json())
      .then((data: string[]) => setSymbols(data))
      .catch(() => {}); // silent fail — user can still type manually
  }, []);

  // ── Derived: live price from latest tick or seed ──
  const livePrice = latestTick?.candle.close ?? null;
  const prevPrice =
    latestTick && seedData?.chart_candles?.length
      ? seedData.chart_candles[seedData.chart_candles.length - 1]?.[4] ?? null
      : null;
  const priceDelta =
    livePrice !== null && prevPrice !== null ? livePrice - prevPrice : null;

  // ── Filtered results ──
  const filtered = query.length > 0
    ? symbols
        .filter((s) => s.toUpperCase().includes(query.toUpperCase()))
        .slice(0, 8)
    : [];

  // ── Selection handler ──
  const selectSymbol = useCallback(
    (sym: string) => {
      switchSymbol(sym);
      setActive(false);
      setQuery("");
      setHighlighted(0);
      inputRef.current?.blur();
    },
    [switchSymbol]
  );

  // ── Keyboard navigation ──
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered.length > 0) {
        selectSymbol(filtered[highlighted]);
      } else if (query.trim()) {
        // Direct symbol entry (not in cached list — try anyway)
        selectSymbol(query.trim().toUpperCase());
      }
    } else if (e.key === "Escape") {
      setActive(false);
      setQuery("");
      inputRef.current?.blur();
    }
  }

  // ── Click outside to dismiss ──
  useEffect(() => {
    if (!active) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setActive(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [active]);

  // ── Reset highlighted index when filtered results change ──
  useEffect(() => {
    setHighlighted(0);
  }, [query]);

  // ── Activate ──
  function activate() {
    setActive(true);
    // Defer focus to next frame so the input is rendered
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  return (
    <div ref={containerRef} className="relative z-50">
      {/* ── THE BAR: fixed height, zero layout shift ── */}
      <div
        className={[
          "flex items-center w-full border-b border-[var(--color-border)]",
          "h-12 sm:h-10", // touch-friendly mobile, compact desktop
          "bg-[var(--color-bg)] px-3 gap-3",
          !active ? "cursor-pointer" : "",
        ].join(" ")}
        onClick={!active ? activate : undefined}
      >
        {active ? (
          /* ── ACTIVE: search input ── */
          <div className="flex items-center w-full gap-2">
            <SearchIcon />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search symbol..."
              className={[
                "flex-1 bg-transparent outline-none font-mono",
                "text-[var(--color-text)] placeholder:text-[var(--color-muted)]",
                // 16px on mobile prevents iOS auto-zoom on focus
                "text-[16px] sm:text-sm",
              ].join(" ")}
              autoComplete="off"
              spellCheck={false}
            />
            <button
              onClick={(e) => {
                e.stopPropagation();
                setActive(false);
                setQuery("");
              }}
              className="text-[var(--color-muted)] hover:text-[var(--color-text)] text-xs font-mono px-1"
            >
              ESC
            </button>
          </div>
        ) : (
          /* ── IDLE: symbol + company + price ── */
          <>
            <SearchIcon />

            {/* Symbol */}
            <span className="font-mono font-bold text-sm sm:text-base text-[var(--color-text)] shrink-0">
              {currentSymbol || "—"}
            </span>

            {/* Company name — hidden on mobile (insufficient width) */}
            {companyName && (
              <span className="hidden sm:block flex-1 min-w-0 truncate text-xs text-[var(--color-muted)]">
                {companyName}
              </span>
            )}

            {/* Spacer on mobile */}
            <div className="flex-1 sm:hidden" />

            {/* Live price + delta */}
            {livePrice !== null && (
              <div className="flex items-center gap-2 shrink-0">
                <span className="font-mono text-sm text-[var(--color-text)] tabular-nums">
                  {formatCurrency(livePrice)}
                </span>
                {priceDelta !== null && (
                  <span
                    className={`font-mono text-xs tabular-nums ${signClass(priceDelta)}`}
                  >
                    {priceDelta >= 0 ? "+" : ""}
                    {priceDelta.toFixed(2)}
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── DROPDOWN: autocomplete results (overlays chart, never pushes grid) ── */}
      {active && query.length > 0 && (
        <div
          className={[
            "absolute left-0 right-0 top-full",
            "bg-[var(--color-panel)] border border-[var(--color-border)] border-t-0",
            "max-h-[320px] overflow-y-auto",
            "shadow-lg shadow-black/40",
          ].join(" ")}
        >
          {filtered.length > 0 ? (
            filtered.map((sym, i) => (
              <button
                key={sym}
                onMouseDown={(e) => {
                  e.preventDefault(); // prevent input blur before selection fires
                  selectSymbol(sym);
                }}
                onMouseEnter={() => setHighlighted(i)}
                className={[
                  "flex items-center w-full px-3 font-mono text-left",
                  // Touch rows on mobile, dense on desktop
                  "h-11 sm:h-9",
                  i === highlighted
                    ? "bg-[var(--color-hover)] text-[var(--color-text)]"
                    : "text-[var(--color-muted)]",
                ].join(" ")}
              >
                <HighlightedSymbol symbol={sym} query={query} />
              </button>
            ))
          ) : (
            <div className="flex items-center px-3 h-9 text-xs text-[var(--color-muted)] font-mono">
              No match
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Magnifying glass icon (inline SVG, no deps) ──

function SearchIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-[var(--color-muted)]"
    >
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

// ── Highlight matched substring in neon green ──

function HighlightedSymbol({ symbol, query }: { symbol: string; query: string }) {
  const idx = symbol.toUpperCase().indexOf(query.toUpperCase());
  if (idx === -1) return <span className="text-sm">{symbol}</span>;

  const before = symbol.slice(0, idx);
  const match = symbol.slice(idx, idx + query.length);
  const after = symbol.slice(idx + query.length);

  return (
    <span className="text-sm">
      {before}
      <span className="text-[var(--color-neon)] font-bold">{match}</span>
      {after}
    </span>
  );
}
