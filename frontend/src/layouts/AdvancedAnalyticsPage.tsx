// ──────────────────────────────────────────────────────────────────────────────
// AdvancedAnalyticsPage — vista a pantalla completa de "Analiticas Avanzadas".
//
// Diseñada para "se come con los ojos": grid de RankingBoards mostrando
// rankings curiosos del dia desde el Gold Layer (BigQuery), cada uno con su
// propio acento de color y tipografia grande para el #1.
// Abajo: tabla densa multi-metric (componente AdvancedAnalytics original).
//
// La pagina vive en /financial/avanzadas. Link de vuelta a /financial/.
// ──────────────────────────────────────────────────────────────────────────────

import RankingBoard from "../components/RankingBoard";
import AdvancedAnalytics from "../components/AdvancedAnalytics";
import LangToggle from "../components/LangToggle";
import { useI18n } from "../i18n";

const fmtPct = (v: number | null) =>
  v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
const fmtVol = (v: number | null) =>
  v == null || !isFinite(v) ? "—" : (v * 100).toFixed(1) + "%";
const fmtRsi = (v: number | null) =>
  v == null || !isFinite(v) ? "—" : v.toFixed(1);
const fmtGap = (v: number | null) =>
  v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
const fmtDist = (v: number | null) =>
  v == null || !isFinite(v) ? "—" : (v * 100).toFixed(1) + "%";

export default function AdvancedAnalyticsPage() {
  const { t } = useI18n();
  return (
    <div className="min-h-dvh w-full bg-[var(--color-bg)] flex flex-col">
      {/* ── Header bar ── */}
      <div
        className={[
          "shrink-0 flex items-center justify-between",
          "h-9 px-4 lg:px-3",
          "bg-[var(--color-bg)] border-b border-[var(--color-border)]",
        ].join(" ")}
      >
        <a
          href="/financial/"
          className={[
            "flex items-center gap-1.5",
            "font-mono text-xs font-semibold",
            "text-[var(--color-blue)] hover:text-[var(--color-text)]",
            "transition-colors no-underline",
          ].join(" ")}
        >
          <span aria-hidden="true">&larr;</span>
          <span>{t("nav.backToDashboard")}</span>
        </a>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] hidden sm:inline">
            {t("nav.breadcrumb")}
          </span>
          <LangToggle />
        </div>
      </div>

      {/* ── HERO ── */}
      <div className="px-4 lg:px-6 pt-5 pb-4 border-b border-[var(--color-border)]">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-2xl sm:text-3xl lg:text-4xl font-mono font-black uppercase tracking-tight text-[var(--color-neon)] leading-none">
            {t("hero.title")}
          </h1>
          <span className="text-[10px] sm:text-[11px] uppercase tracking-widest text-[var(--color-muted)] font-mono">
            {t("hero.tagline")}
          </span>
        </div>
        <p className="mt-3 text-[12px] sm:text-[13px] text-[var(--color-text)] max-w-3xl leading-relaxed">
          {t("hero.desc")} <strong className="text-[var(--color-neon)]">{t("hero.descLayer")}</strong>
          {t("hero.descMiddle")}{" "}
          <em className="text-[var(--color-yellow)] not-italic font-semibold">{t("hero.descEmphasis")}</em>{" "}
          {t("hero.descEnd")}
        </p>

        {/* ── Mini-glosario de las tres capas (legibilidad para el visitante nuevo) ── */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2 max-w-3xl">
          <div className="border border-[var(--color-border)] px-3 py-2 bg-[var(--color-panel)]">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-yellow)]">
              {t("z.intra")}
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              {t("z.intraDesc")} <strong className="text-[var(--color-text)]">{t("z.intraEmphasis")}</strong> {t("z.intraWindow")}
            </p>
          </div>
          <div className="border border-[var(--color-border)] px-3 py-2 bg-[var(--color-panel)]">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-yellow)]">
              {t("z.cross")}
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              {t("z.crossDesc")} <strong className="text-[var(--color-text)]">{t("z.crossEmphasis")}</strong>{t("z.crossEnd")}
            </p>
          </div>
          <div className="border border-[var(--color-neon)]/40 px-3 py-2 bg-[var(--color-neon)]/5">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-neon)]">
              {t("z.ofz")}
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              {t("z.ofzDesc")} <strong className="text-[var(--color-text)]">{t("z.ofzEmphasis")}</strong>{t("z.ofzEnd")}
            </p>
          </div>
        </div>

        <p className="mt-3 text-[10px] sm:text-[11px] text-[var(--color-muted)] font-mono">
          {t("hero.source")} <code className="text-[var(--color-blue)]">financial_marts.fact_derived_metrics</code>
          {" "}{t("hero.refreshNote")} <span className="text-[var(--color-yellow)]">?</span> {t("hero.refreshEnd")}
        </p>
      </div>

      {/* ── GRID DE RANKINGS ── */}
      <div className="px-4 lg:px-6 py-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">

        <RankingBoard
          title={t("rank.overbought.title")}
          subtitle={t("rank.overbought.sub")}
          help={t("rank.overbought.help")}
          metric="rsi_14"
          filter="pos"
          accent="neon"
          metricShort="RSI"
          formatMetric={fmtRsi}
        />

        <RankingBoard
          title={t("rank.oversold.title")}
          subtitle={t("rank.oversold.sub")}
          help={t("rank.oversold.help")}
          metric="rsi_14"
          filter="neg"
          accent="red"
          metricShort="RSI"
          formatMetric={fmtRsi}
        />

        <RankingBoard
          title={t("rank.vol1m.title")}
          subtitle={t("rank.vol1m.sub")}
          help={t("rank.vol1m.help")}
          metric="vol_1m"
          filter="abs"
          accent="yellow"
          metricShort="vol"
          formatMetric={fmtVol}
        />

        <RankingBoard
          title={t("rank.rally.title")}
          subtitle={t("rank.rally.sub")}
          help={t("rank.rally.help")}
          metric="ret_1m"
          filter="pos"
          accent="neon"
          metricShort="1M"
          formatMetric={fmtPct}
        />

        <RankingBoard
          title={t("rank.drop.title")}
          subtitle={t("rank.drop.sub")}
          help={t("rank.drop.help")}
          metric="ret_1m"
          filter="neg"
          accent="red"
          metricShort="1M"
          formatMetric={fmtPct}
        />

        <RankingBoard
          title={t("rank.sma200.title")}
          subtitle={t("rank.sma200.sub")}
          help={t("rank.sma200.help")}
          metric="sma_200_gap"
          filter="abs"
          accent="blue"
          metricShort="gap"
          formatMetric={fmtGap}
        />

        <RankingBoard
          title={t("rank.highDist.title")}
          subtitle={t("rank.highDist.sub")}
          help={t("rank.highDist.help")}
          metric="high_dist_1y"
          filter="abs"
          accent="neon"
          metricShort="dist"
          formatMetric={fmtDist}
        />

        <RankingBoard
          title={t("rank.range.title")}
          subtitle={t("rank.range.sub")}
          help={t("rank.range.help")}
          metric="range_intraday"
          filter="abs"
          accent="yellow"
          metricShort="rng"
          formatMetric={fmtGap}
        />

        <RankingBoard
          title={t("rank.vol3m.title")}
          subtitle={t("rank.vol3m.sub")}
          help={t("rank.vol3m.help")}
          metric="vol_3m"
          filter="abs"
          accent="blue"
          metricShort="vol"
          formatMetric={fmtVol}
        />
      </div>

      {/* ── DIVIDER ── */}
      <div className="px-4 lg:px-6 pt-4">
        <div className="border-t border-[var(--color-border)] pt-4 pb-2">
          <h2 className="text-sm font-mono uppercase tracking-widest font-bold text-[var(--color-text)]">
            {t("table.title")}
          </h2>
          <p className="text-[11px] text-[var(--color-muted)] mt-1">
            {t("table.desc")} <code>/analytics/anomalies</code>
            {t("table.descEnd")}
          </p>
        </div>
      </div>

      {/* ── TABLA DENSA ── */}
      <div className="px-0 lg:px-6 pb-6">
        <AdvancedAnalytics />
      </div>

      {/* ── Footer ── */}
      <div
        className="shrink-0 mt-auto px-4 py-2 text-[10px] uppercase tracking-wider text-[var(--color-muted)] border-t border-[var(--color-border)] font-mono"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {t("table.footer")}
      </div>
    </div>
  );
}
