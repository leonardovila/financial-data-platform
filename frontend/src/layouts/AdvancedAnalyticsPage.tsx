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
          <span>volver al dashboard</span>
        </a>
        <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)]">
          /financial/avanzadas · gold · bigquery
        </span>
      </div>

      {/* ── HERO ── */}
      <div className="px-4 lg:px-6 pt-5 pb-4 border-b border-[var(--color-border)]">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-2xl sm:text-3xl lg:text-4xl font-mono font-black uppercase tracking-tight text-[var(--color-neon)] leading-none">
            Analiticas Avanzadas
          </h1>
          <span className="text-[10px] sm:text-[11px] uppercase tracking-widest text-[var(--color-muted)] font-mono">
            outlier detection · z-of-z layer · cross-asset
          </span>
        </div>
        <p className="mt-3 text-[12px] sm:text-[13px] text-[var(--color-text)] max-w-3xl leading-relaxed">
          Rankings del dia segun la <strong className="text-[var(--color-neon)]">capa z_of_z</strong>:
          la rareza de la rareza. No mostramos el simbolo mas sobrecomprado en RSI —
          mostramos al simbolo cuya sobrecompra es{" "}
          <em className="text-[var(--color-yellow)] not-italic font-semibold">anormalmente extrema</em>{" "}
          incluso para un dia que YA esta lleno de sobrecompra.
        </p>

        {/* ── Mini-glosario de las tres capas (legibilidad para el visitante nuevo) ── */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2 max-w-3xl">
          <div className="border border-[var(--color-border)] px-3 py-2 bg-[var(--color-panel)]">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-yellow)]">
              z_intra
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              Que tan raro esta el simbolo vs su <strong className="text-[var(--color-text)]">propia historia</strong> (252d).
            </p>
          </div>
          <div className="border border-[var(--color-border)] px-3 py-2 bg-[var(--color-panel)]">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-yellow)]">
              z_cross
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              Que tan raro esta vs el <strong className="text-[var(--color-text)]">resto del universo HOY</strong>.
            </p>
          </div>
          <div className="border border-[var(--color-neon)]/40 px-3 py-2 bg-[var(--color-neon)]/5">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--color-neon)]">
              z_of_z ★
            </div>
            <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-snug">
              La <strong className="text-[var(--color-text)]">rareza de la rareza</strong>: anomalia dentro de anomalia.
            </p>
          </div>
        </div>

        <p className="mt-3 text-[10px] sm:text-[11px] text-[var(--color-muted)] font-mono">
          source: <code className="text-[var(--color-blue)]">financial_marts.fact_derived_metrics</code>
          {" "}· refrescado 1×/dia · clic en el <span className="text-[var(--color-yellow)]">?</span> de cada card para mas detalle
        </p>
      </div>

      {/* ── GRID DE RANKINGS ── */}
      <div className="px-4 lg:px-6 py-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">

        <RankingBoard
          title="MAS SOBRECOMPRADOS"
          subtitle="RSI 14 — anomalia positiva extrema"
          help="Simbolos cuyo RSI de hoy es anormalmente alto en TRES capas: vs su propia historia (z_intra), vs el resto del universo HOY (z_cross), y la rareza de esa rareza (z_of_z). RSI > 70 ya es 'sobrecomprado' clasico — aca rankeamos quien esta MAS sobrecomprado de lo esperable."
          metric="rsi_14"
          filter="pos"
          accent="neon"
          metricShort="RSI"
          formatMetric={fmtRsi}
        />

        <RankingBoard
          title="MAS SOBREVENDIDOS"
          subtitle="RSI 14 — anomalia negativa extrema"
          help="Lo opuesto: RSI bajo Y anormalmente bajo. Tipicamente RSI < 30 = sobrevendido. Aca rankeamos por |z_of_z|: candidatos a rebote tecnico segun el detector."
          metric="rsi_14"
          filter="neg"
          accent="red"
          metricShort="RSI"
          formatMetric={fmtRsi}
        />

        <RankingBoard
          title="VOLATILIDAD ANOMALA"
          subtitle="Vol 1M — z_of_z absoluto"
          help="Volatilidad anualizada del ultimo mes (21 dias habiles). Rankeamos por |z_of_z|: simbolos cuya vol esta lejos de la suya historica Y de la del universo. Util para detectar regime shifts."
          metric="vol_1m"
          filter="abs"
          accent="yellow"
          metricShort="vol"
          formatMetric={fmtVol}
        />

        <RankingBoard
          title="RALLY DEL MES"
          subtitle="Retorno 1M — anomalia positiva"
          help="Retorno de los ultimos 21 dias habiles, con z_of_z positivo extremo. No es solo el que mas subio: es el que mas subio comparado con su perfil tipico Y comparado con como se comporto el universo este mes."
          metric="ret_1m"
          filter="pos"
          accent="neon"
          metricShort="1M"
          formatMetric={fmtPct}
        />

        <RankingBoard
          title="CAIDA DEL MES"
          subtitle="Retorno 1M — anomalia negativa"
          help="Espejo del rally: caidas anormalmente fuertes en 1 mes. Si el universo entero bajo, una caida del 5% es normal; aca aparecen las que se desviaron del comportamiento general."
          metric="ret_1m"
          filter="neg"
          accent="red"
          metricShort="1M"
          formatMetric={fmtPct}
        />

        <RankingBoard
          title="GAP vs SMA 200"
          subtitle="Distancia anomala al promedio 200d"
          help="(precio − SMA200) / SMA200. Indicador clasico de tendencia largoplacista (>0 = bull, <0 = bear). Rankeamos por |z_of_z|: quien esta MAS lejos de su promedio largo de lo que su historia justifica."
          metric="sma_200_gap"
          filter="abs"
          accent="blue"
          metricShort="gap"
          formatMetric={fmtGap}
        />

        <RankingBoard
          title="CERCA DEL MAXIMO 1Y"
          subtitle="Distancia al techo de 52 semanas"
          help="(precio − max_52w) / max_52w. 0% = nuevo maximo de 52 semanas. Rankeamos por |z_of_z|: quien esta tocando techo (o piso) de manera estadisticamente rara."
          metric="high_dist_1y"
          filter="abs"
          accent="neon"
          metricShort="dist"
          formatMetric={fmtDist}
        />

        <RankingBoard
          title="RANGO INTRADIA RARO"
          subtitle="(high − low) / close — sesion atipica"
          help="Amplitud de la sesion del dia normalizada al precio. Sesion ancha = mucha pelea entre buy/sell. z_of_z extremo = ese simbolo tuvo un dia mas (o menos) volatil de lo que cualquiera esperaria."
          metric="range_intraday"
          filter="abs"
          accent="yellow"
          metricShort="rng"
          formatMetric={fmtGap}
        />

        <RankingBoard
          title="VOLATILIDAD 3M"
          subtitle="Regimen de volatilidad anomalo"
          help="Volatilidad anualizada de 63 dias. Captura cambios de regimen mas estables que la de 1M. z_of_z extremo = ese simbolo entro/salio de un regimen de vol distinto al del resto."
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
            tabla cruda · multi-metrica
          </h2>
          <p className="text-[11px] text-[var(--color-muted)] mt-1">
            La misma data servida desde el endpoint <code>/analytics/anomalies</code>,
            con selector libre de metrica y las tres capas de z-score (intra / cross / of_z).
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
        gold layer · bigquery · financial_marts.fact_derived_metrics · refrescado 1×/dia
      </div>
    </div>
  );
}
