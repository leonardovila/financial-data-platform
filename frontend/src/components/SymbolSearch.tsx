// ──────────────────────────────────────────────────────────────────────────────
// FRONT-008: SymbolSearch — persistent inline header bar
//
// Idle:   [🔍 BTC — Bitcoin   $67,432.10 ▲+1.23%]
// Active: [Search ticker or company...____________] + dropdown overlay
//
// During switch (seedData=null): shows pendingSymbolDisplay ("AAPL — Apple Inc")
// ──────────────────────────────────────────────────────────────────────────────

import { useState, useRef, useEffect, useCallback } from "react";
import { useWsStore } from "../stores/wsStore";
import { formatCurrency } from "../lib/formatters";
import { useI18n } from "../i18n";

const API_BASE =
  import.meta.env.VITE_API_URL ?? `${window.location.origin}`;

interface SymbolEntry {
  symbol: string;
  name: string | null;
}

export default function SymbolSearch() {
  const { t } = useI18n();
  const currentSymbol = useWsStore((s) => s.currentSymbol);
  const companyName = useWsStore((s) => s.companyName);
  const pendingSymbolDisplay = useWsStore((s) => s.pendingSymbolDisplay);
  const latestTick = useWsStore((s) => s.latestTick);
  const seedData = useWsStore((s) => s.seedData);
  const switchSymbol = useWsStore((s) => s.switchSymbol);

  const [active, setActive] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [symbols, setSymbols] = useState<SymbolEntry[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Fetch symbol list once on mount ──
  useEffect(() => {
    fetch(`${API_BASE}/symbols`)
      .then((r) => r.json())
      .then((data: SymbolEntry[] | string[]) => {
        if (data.length > 0 && typeof data[0] === "string") {
          setSymbols((data as string[]).map((s) => ({ symbol: s, name: null })));
        } else {
          setSymbols(data as SymbolEntry[]);
        }
      })
      .catch(() => {});
  }, []);

  // ── Derived: live price ──
  const livePrice = latestTick?.candle.close ?? null;

  // ── Derived: display text for idle state ──
  // During switch (seedData=null): show pendingSymbolDisplay
  // After seed arrives: show currentSymbol + companyName from live stream
  const isLoading = !seedData && !!currentSymbol;
  const displaySymbol = currentSymbol || "—";
  const displayCompany = isLoading ? null : companyName;
  const displayPending = isLoading ? pendingSymbolDisplay : null;

  // ── Filtered results (case-insensitive, search ticker OR company name) ──
  const filtered =
    query.length > 0
      ? symbols
          .filter((e) => {
            const q = query.toLowerCase();
            return (
              e.symbol.toLowerCase().includes(q) ||
              (e.name?.toLowerCase().includes(q) ?? false)
            );
          })
          .slice(0, 8)
      : [];

  // ── Selection: pass both symbol and company name to store ──
  const selectSymbol = useCallback(
    (sym: string, name?: string | null) => {
      switchSymbol(sym, name);
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
        const entry = filtered[highlighted];
        selectSymbol(entry.symbol, entry.name);
      } else if (query.trim()) {
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
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setActive(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [active]);

  useEffect(() => {
    setHighlighted(0);
  }, [query]);

  function activate() {
    setActive(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  return (
    <div ref={containerRef} className="relative z-50">
      <div
        className={[
          "flex items-center w-full border-b border-[var(--color-border)]",
          "h-12 sm:h-10",
          "bg-[var(--color-bg)] px-3 gap-3",
          !active ? "cursor-pointer" : "",
        ].join(" ")}
        onClick={!active ? activate : undefined}
      >
        {active ? (
          <div className="flex items-center w-full gap-2">
            <SearchIcon />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("search.placeholder")}
              className={[
                "flex-1 bg-transparent outline-none font-mono",
                "text-[var(--color-text)] placeholder:text-[var(--color-muted)]",
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
          <>
            <SearchIcon />

            {/* Symbol + Company (or pending display during switch) */}
            <div className="flex items-center gap-1.5 flex-1 min-w-0">
              <span className="font-mono font-bold text-sm sm:text-base text-[var(--color-text)] shrink-0">
                {displaySymbol}
              </span>
              {displayPending && (
                <span className="truncate text-xs text-[var(--color-yellow)] animate-pulse">
                  {displayPending.includes("—")
                    ? displayPending.split("—").slice(1).join("—").trim()
                    : t("search.loading")}
                </span>
              )}
              {displayCompany && (
                <span className="truncate text-sm sm:text-base text-[var(--color-text)]">
                  — {displayCompany}
                </span>
              )}
            </div>

            {/* Live price (limpio, sin deltas fantasma) */}
            {livePrice !== null && (
              <div className="flex items-center gap-2 shrink-0">
                <span className="font-mono text-sm text-[var(--color-text)] tabular-nums">
                  {formatCurrency(livePrice)}
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── DROPDOWN ── */}
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
            filtered.map((entry, i) => (
              <button
                key={entry.symbol}
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectSymbol(entry.symbol, entry.name);
                }}
                onMouseEnter={() => setHighlighted(i)}
                className={[
                  "flex items-center gap-2 w-full px-3 font-mono text-left",
                  "h-11 sm:h-9",
                  i === highlighted
                    ? "bg-[var(--color-hover)] text-[var(--color-text)]"
                    : "text-[var(--color-muted)]",
                ].join(" ")}
              >
                <HighlightedSymbol symbol={entry.symbol} query={query} />
                {entry.name && (
                  <span className="truncate text-xs text-[var(--color-muted)]">
                    — {entry.name}
                  </span>
                )}
              </button>
            ))
          ) : (
            <div className="flex items-center px-3 h-9 text-xs text-[var(--color-muted)] font-mono">
              {t("search.noMatch")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

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

function HighlightedSymbol({
  symbol,
  query,
}: {
  symbol: string;
  query: string;
}) {
  const idx = symbol.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <span className="text-sm font-bold">{symbol}</span>;

  const before = symbol.slice(0, idx);
  const match = symbol.slice(idx, idx + query.length);
  const after = symbol.slice(idx + query.length);

  return (
    <span className="text-sm font-bold">
      {before}
      <span className="text-[var(--color-neon)]">{match}</span>
      {after}
    </span>
  );
}
