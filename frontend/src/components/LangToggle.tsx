// ──────────────────────────────────────────────────────────────────────────────
// LangToggle — CSS pill-slider for ES/EN language switch.
//
// Design: two-option pill with sliding thumb (neon-green accent).
// Persistence handled by I18nProvider (localStorage).
// Position: absolutely placed by the consuming layout, not self-positioning.
// ──────────────────────────────────────────────────────────────────────────────

import { useI18n } from "../i18n";
import type { Lang } from "../i18n";

export default function LangToggle() {
  const { lang, setLang } = useI18n();

  return (
    <div
      className="lang-toggle"
      role="radiogroup"
      aria-label="Language"
    >
      <div
        className="lang-toggle__thumb"
        style={{ transform: lang === "en" ? "translateX(0)" : "translateX(100%)" }}
      />
      <button
        type="button"
        role="radio"
        aria-checked={lang === "en"}
        className={`lang-toggle__opt ${lang === "en" ? "lang-toggle__opt--active" : ""}`}
        onClick={() => setLang("en" as Lang)}
      >
        EN
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={lang === "es"}
        className={`lang-toggle__opt ${lang === "es" ? "lang-toggle__opt--active" : ""}`}
        onClick={() => setLang("es" as Lang)}
      >
        ES
      </button>
    </div>
  );
}
