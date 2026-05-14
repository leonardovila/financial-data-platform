// ──────────────────────────────────────────────────────────────────────────────
// LangToggle — pill-slider for ES/EN language switch.
//
// 100% Tailwind inline classes — no custom CSS dependency.
// Neon-green sliding thumb, dark text on active, muted on inactive.
// ──────────────────────────────────────────────────────────────────────────────

import { useI18n } from "../i18n";

export default function LangToggle() {
  const { lang, setLang } = useI18n();

  return (
    <div
      className="relative inline-flex items-center h-7 rounded-full border border-[var(--color-border)] bg-[var(--color-panel)] overflow-hidden"
      role="radiogroup"
      aria-label="Language"
    >
      {/* Sliding thumb */}
      <div
        className="absolute top-[2px] left-[2px] w-[calc(50%-2px)] h-[calc(100%-4px)] rounded-full bg-[var(--color-neon)] transition-transform duration-200 ease-out pointer-events-none"
        style={{ transform: lang === "en" ? "translateX(0)" : "translateX(100%)" }}
      />

      <button
        type="button"
        role="radio"
        aria-checked={lang === "en"}
        onClick={() => setLang("en")}
        className={[
          "relative z-10 flex items-center justify-center",
          "w-9 h-full font-mono text-[11px] font-bold tracking-wide",
          "border-none bg-transparent cursor-pointer transition-colors duration-200",
          lang === "en" ? "text-[var(--color-bg)]" : "text-[var(--color-muted)]",
        ].join(" ")}
      >
        EN
      </button>

      <button
        type="button"
        role="radio"
        aria-checked={lang === "es"}
        onClick={() => setLang("es")}
        className={[
          "relative z-10 flex items-center justify-center",
          "w-9 h-full font-mono text-[11px] font-bold tracking-wide",
          "border-none bg-transparent cursor-pointer transition-colors duration-200",
          lang === "es" ? "text-[var(--color-bg)]" : "text-[var(--color-muted)]",
        ].join(" ")}
      >
        ES
      </button>
    </div>
  );
}
