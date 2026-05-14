// ──────────────────────────────────────────────────────────────────────────────
// FRONT-009: StatusBar — connection status, symbol, tick count, latency
//
// Desktop (sm+): h-6. [dot LIVE] [BTC] [Ticks: 142] [Last: 3s ago]
// Mobile (<sm):  h-7. [dot] [BTC] [142] [3s] — labels dropped, values only.
// safe-area-inset-bottom for iPhone home indicator.
// ──────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from "react";
import { useWsStore } from "../stores/wsStore";
import { useI18n } from "../i18n";
import type { TKey } from "../i18n";

const STATUS_CONFIG = {
  connected: { color: "bg-[var(--color-neon)]", labelKey: "status.live" as TKey },
  connecting: { color: "bg-[var(--color-yellow)]", labelKey: "status.connecting" as TKey },
  reconnecting: { color: "bg-[var(--color-yellow)]", labelKey: "status.reconnecting" as TKey },
  disconnected: { color: "bg-[var(--color-red)]", labelKey: "status.offline" as TKey },
} as const;

export default function StatusBar() {
  const { t } = useI18n();
  const status = useWsStore((s) => s.status);
  const currentSymbol = useWsStore((s) => s.currentSymbol);
  const tickHistory = useWsStore((s) => s.tickHistory);
  const latestTickTs = useWsStore((s) => s.latestTick?.ts ?? null);

  const [elapsed, setElapsed] = useState<number | null>(null);

  // ── Live clock: "Xs ago" relative to last tick ──
  useEffect(() => {
    if (latestTickTs === null) {
      setElapsed(null);
      return;
    }

    // Immediate update
    setElapsed(Math.floor(Date.now() / 1000 - latestTickTs));

    const iv = setInterval(() => {
      setElapsed(Math.floor(Date.now() / 1000 - latestTickTs));
    }, 1000);

    return () => clearInterval(iv);
  }, [latestTickTs]);

  const { color, labelKey } = STATUS_CONFIG[status];
  const tickCount = tickHistory.length;

  return (
    <div
      className={[
        "flex items-center justify-between px-3 font-mono",
        "h-full text-[10px]",
        "bg-[var(--color-bg)] border-t border-[var(--color-border)]",
        "text-[var(--color-muted)]",
      ].join(" ")}
    >
      {/* Left: status dot + label */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${color} ${status === "connected" ? "pulse" : ""}`} />
        <span className="hidden sm:inline uppercase tracking-wider">{t(labelKey)}</span>
      </div>

      {/* Center: symbol */}
      <span className="truncate text-center text-[var(--color-text)]">
        {currentSymbol || "—"}
      </span>

      {/* Right: tick count + elapsed */}
      <div className="flex items-center gap-3 shrink-0">
        {tickCount > 0 && (
          <span>
            <span className="hidden sm:inline">{t("status.ticks")}</span>
            {tickCount}
          </span>
        )}
        {elapsed !== null && (
          <span>
            <span className="hidden sm:inline">{t("status.last")}</span>
            {elapsed}s
          </span>
        )}
      </div>
    </div>
  );
}
