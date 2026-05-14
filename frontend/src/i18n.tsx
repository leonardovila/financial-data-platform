// ──────────────────────────────────────────────────────────────────────────────
// i18n — lightweight ES/EN internationalization via React Context.
//
// No external i18n library. Flat dict with dot-notation keys.
// Persistence: localStorage('lang'). Default: 'en'.
// FOUC prevention: inline script in index.html sets <html lang> before React.
//
// Usage:
//   import { useI18n } from '../i18n'
//   const { t } = useI18n()
//   <span>{t('nav.back')}</span>
// ──────────────────────────────────────────────────────────────────────────────

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export type Lang = "en" | "es";

const dict = {
  // ── Navigation ──
  "nav.backToSite":            { en: "leonardovila.com",                       es: "leonardovila.com" },
  "nav.backToDashboard":       { en: "back to dashboard",                     es: "volver al dashboard" },
  "nav.breadcrumb":            { en: "/financial/avanzadas · gold · bigquery", es: "/financial/avanzadas · gold · bigquery" },

  // ── Dashboard CTA ──
  "cta.title":                 { en: "view advanced analytics",               es: "ver analiticas avanzadas" },
  "cta.subtitle":              { en: "outlier detector · z_intra · z_cross · z_of_z · gold layer (bigquery)", es: "detector de outliers · z_intra · z_cross · z_of_z · gold layer (bigquery)" },
  "cta.enter":                 { en: "enter",                                 es: "entrar" },

  // ── Symbol Search ──
  "search.placeholder":        { en: "Search ticker or company...",           es: "Buscar ticker o empresa..." },
  "search.loading":            { en: "Loading...",                            es: "Cargando..." },
  "search.noMatch":            { en: "No match",                             es: "Sin resultados" },

  // ── Fundamentals Bar ──
  "fund.mktCap":               { en: "Mkt Cap",                              es: "Cap. Mercado" },
  "fund.pe":                   { en: "P/E",                                  es: "P/E" },
  "fund.eps":                  { en: "EPS",                                  es: "EPS" },
  "fund.shares":               { en: "Shares",                               es: "Acciones" },
  "fund.sector":               { en: "Sector",                               es: "Sector" },
  "fund.industry":             { en: "Industry",                             es: "Industria" },

  // ── Status Bar ──
  "status.live":               { en: "LIVE",                                 es: "EN VIVO" },
  "status.connecting":         { en: "CONNECTING",                           es: "CONECTANDO" },
  "status.reconnecting":       { en: "RECONNECTING",                        es: "RECONECTANDO" },
  "status.offline":            { en: "OFFLINE",                              es: "DESCONECTADO" },
  "status.ticks":              { en: "Ticks: ",                              es: "Ticks: " },
  "status.last":               { en: "Last: ",                               es: "Hace: " },

  // ── Metrics Grid Tabs ──
  "metrics.performance":       { en: "PERFORMANCE",                          es: "RENDIMIENTO" },
  "metrics.volatility":        { en: "VOLATILITY",                           es: "VOLATILIDAD" },
  "metrics.momentum":          { en: "MOMENTUM",                             es: "MOMENTUM" },

  // ── Performance Rows ──
  "perf.1d":                   { en: "Price Change 1D",                      es: "Var. Precio 1D" },
  "perf.1w":                   { en: "Price Change 1W",                      es: "Var. Precio 1S" },
  "perf.1m":                   { en: "Price Change 1M",                      es: "Var. Precio 1M" },
  "perf.3m":                   { en: "Price Change 3M",                      es: "Var. Precio 3M" },
  "perf.6m":                   { en: "Price Change 6M",                      es: "Var. Precio 6M" },
  "perf.1y":                   { en: "Price Change 1Y",                      es: "Var. Precio 1A" },

  // ── Volatility Rows ──
  "vol.range":                 { en: "Range",                                es: "Rango" },
  "vol.1w":                    { en: "Volatility 1W",                        es: "Volatilidad 1S" },
  "vol.1m":                    { en: "Volatility 1M",                        es: "Volatilidad 1M" },
  "vol.3m":                    { en: "Volatility 3M",                        es: "Volatilidad 3M" },
  "vol.6m":                    { en: "Volatility 6M",                        es: "Volatilidad 6M" },
  "vol.1y":                    { en: "Volatility 1Y",                        es: "Volatilidad 1A" },

  // ── Momentum Rows ──
  "mom.rsi":                   { en: "RSI 14",                               es: "RSI 14" },
  "mom.sma20":                 { en: "SMA 20 Gap",                           es: "Gap SMA 20" },
  "mom.sma50":                 { en: "SMA 50 Gap",                           es: "Gap SMA 50" },
  "mom.sma200":                { en: "SMA 200 Gap",                          es: "Gap SMA 200" },
  "mom.high1m":                { en: "Off 1M High",                          es: "Dist. Máx 1M" },
  "mom.high1y":                { en: "Off 52W High",                         es: "Dist. Máx 52S" },

  // ── Live Feed ──
  "feed.title":                { en: "LIVE PRICE FEED",                      es: "FEED DE PRECIOS EN VIVO" },
  "feed.awaitingTitle":        { en: "Awaiting Market Data",                 es: "Esperando Datos del Mercado" },
  "feed.awaitingDesc":         { en: "If there's no activity after a few seconds, the traditional market is currently closed.", es: "Si no hay actividad después de unos segundos, el mercado tradicional está cerrado." },
  "feed.testEngine":           { en: "Test the 24/7 Engine",                 es: "Probar el Motor 24/7" },
  "feed.searchBtc":            { en: "for live crypto flow",                 es: "para ver cripto en vivo" },
  "feed.marketClosed":         { en: "Market closed. Search",                es: "Mercado cerrado. Buscar" },
  "feed.for247":               { en: "for 24/7 flow.",                       es: "para flujo 24/7." },
  "feed.time":                 { en: "Time",                                 es: "Hora" },
  "feed.price":                { en: "Price",                                es: "Precio" },
  "feed.delta":                { en: "Delta",                                es: "Delta" },

  // ── Ranking Board ──
  "ranking.loading":           { en: "loading…",                             es: "cargando…" },
  "ranking.noResults":         { en: "no results",                           es: "sin resultados" },

  // ── Ranking Board Titles ──
  "rank.overbought.title":     { en: "MOST OVERBOUGHT",                     es: "MAS SOBRECOMPRADOS" },
  "rank.overbought.sub":       { en: "RSI 14 — extreme positive anomaly",   es: "RSI 14 — anomalia positiva extrema" },
  "rank.overbought.help":      { en: "Symbols whose RSI today is abnormally high across THREE layers: vs its own history (z_intra), vs the rest of the universe TODAY (z_cross), and the rarity of that rarity (z_of_z). RSI > 70 is classic 'overbought' — here we rank who is MORE overbought than expected.", es: "Simbolos cuyo RSI de hoy es anormalmente alto en TRES capas: vs su propia historia (z_intra), vs el resto del universo HOY (z_cross), y la rareza de esa rareza (z_of_z). RSI > 70 ya es 'sobrecomprado' clasico — aca rankeamos quien esta MAS sobrecomprado de lo esperable." },

  "rank.oversold.title":       { en: "MOST OVERSOLD",                       es: "MAS SOBREVENDIDOS" },
  "rank.oversold.sub":         { en: "RSI 14 — extreme negative anomaly",   es: "RSI 14 — anomalia negativa extrema" },
  "rank.oversold.help":        { en: "The opposite: low RSI AND abnormally low. Typically RSI < 30 = oversold. We rank by |z_of_z|: technical bounce candidates according to the detector.", es: "Lo opuesto: RSI bajo Y anormalmente bajo. Tipicamente RSI < 30 = sobrevendido. Aca rankeamos por |z_of_z|: candidatos a rebote tecnico segun el detector." },

  "rank.vol1m.title":          { en: "ANOMALOUS VOLATILITY",                es: "VOLATILIDAD ANOMALA" },
  "rank.vol1m.sub":            { en: "Vol 1M — absolute z_of_z",            es: "Vol 1M — z_of_z absoluto" },
  "rank.vol1m.help":           { en: "Annualized volatility over the last month (21 trading days). Ranked by |z_of_z|: symbols whose vol is far from both their historical norm AND the universe. Useful for detecting regime shifts.", es: "Volatilidad anualizada del ultimo mes (21 dias habiles). Rankeamos por |z_of_z|: simbolos cuya vol esta lejos de la suya historica Y de la del universo. Util para detectar regime shifts." },

  "rank.rally.title":          { en: "RALLY OF THE MONTH",                  es: "RALLY DEL MES" },
  "rank.rally.sub":            { en: "Return 1M — positive anomaly",        es: "Retorno 1M — anomalia positiva" },
  "rank.rally.help":           { en: "Return over the last 21 trading days, with extreme positive z_of_z. Not just the biggest gainer: the one that gained the most compared to its typical profile AND compared to how the universe behaved this month.", es: "Retorno de los ultimos 21 dias habiles, con z_of_z positivo extremo. No es solo el que mas subio: es el que mas subio comparado con su perfil tipico Y comparado con como se comporto el universo este mes." },

  "rank.drop.title":           { en: "DROP OF THE MONTH",                   es: "CAIDA DEL MES" },
  "rank.drop.sub":             { en: "Return 1M — negative anomaly",        es: "Retorno 1M — anomalia negativa" },
  "rank.drop.help":            { en: "Mirror of the rally: abnormally strong 1-month drops. If the whole universe dropped, a 5% decline is normal; here appear those that deviated from general behavior.", es: "Espejo del rally: caidas anormalmente fuertes en 1 mes. Si el universo entero bajo, una caida del 5% es normal; aca aparecen las que se desviaron del comportamiento general." },

  "rank.sma200.title":         { en: "GAP vs SMA 200",                      es: "GAP vs SMA 200" },
  "rank.sma200.sub":           { en: "Anomalous distance to 200d average",  es: "Distancia anomala al promedio 200d" },
  "rank.sma200.help":          { en: "(price − SMA200) / SMA200. Classic long-term trend indicator (>0 = bull, <0 = bear). Ranked by |z_of_z|: who is FURTHER from their long average than their history justifies.", es: "(precio − SMA200) / SMA200. Indicador clasico de tendencia largoplacista (>0 = bull, <0 = bear). Rankeamos por |z_of_z|: quien esta MAS lejos de su promedio largo de lo que su historia justifica." },

  "rank.highDist.title":       { en: "NEAR 1Y HIGH",                        es: "CERCA DEL MAXIMO 1Y" },
  "rank.highDist.sub":         { en: "Distance to 52-week ceiling",         es: "Distancia al techo de 52 semanas" },
  "rank.highDist.help":        { en: "(price − max_52w) / max_52w. 0% = new 52-week high. Ranked by |z_of_z|: who is hitting ceiling (or floor) in a statistically unusual way.", es: "(precio − max_52w) / max_52w. 0% = nuevo maximo de 52 semanas. Rankeamos por |z_of_z|: quien esta tocando techo (o piso) de manera estadisticamente rara." },

  "rank.range.title":          { en: "UNUSUAL INTRADAY RANGE",              es: "RANGO INTRADIA RARO" },
  "rank.range.sub":            { en: "(high − low) / close — atypical session", es: "(high − low) / close — sesion atipica" },
  "rank.range.help":           { en: "Session amplitude normalized to price. Wide session = heavy buy/sell contention. Extreme z_of_z = that symbol had a more (or less) volatile day than anyone would expect.", es: "Amplitud de la sesion del dia normalizada al precio. Sesion ancha = mucha pelea entre buy/sell. z_of_z extremo = ese simbolo tuvo un dia mas (o menos) volatil de lo que cualquiera esperaria." },

  "rank.vol3m.title":          { en: "VOLATILITY 3M",                       es: "VOLATILIDAD 3M" },
  "rank.vol3m.sub":            { en: "Anomalous volatility regime",         es: "Regimen de volatilidad anomalo" },
  "rank.vol3m.help":           { en: "Annualized volatility over 63 days. Captures more stable regime shifts than 1M. Extreme z_of_z = that symbol entered/exited a vol regime different from the rest.", es: "Volatilidad anualizada de 63 dias. Captura cambios de regimen mas estables que la de 1M. z_of_z extremo = ese simbolo entro/salio de un regimen de vol distinto al del resto." },

  // ── Advanced Analytics Hero ──
  "hero.title":                { en: "Advanced Analytics",                   es: "Analiticas Avanzadas" },
  "hero.tagline":              { en: "outlier detection · z-of-z layer · cross-asset", es: "outlier detection · z-of-z layer · cross-asset" },
  "hero.desc":                 { en: "Today's rankings by the",              es: "Rankings del dia segun la" },
  "hero.descLayer":            { en: "z_of_z layer",                        es: "capa z_of_z" },
  "hero.descMiddle":           { en: ": the rarity of the rarity. We don't show the most overbought symbol by RSI — we show the symbol whose overbought-ness is", es: ": la rareza de la rareza. No mostramos el simbolo mas sobrecomprado en RSI — mostramos al simbolo cuya sobrecompra es" },
  "hero.descEmphasis":         { en: "abnormally extreme",                  es: "anormalmente extrema" },
  "hero.descEnd":              { en: "even for a day that is ALREADY full of overbought-ness.", es: "incluso para un dia que YA esta lleno de sobrecompra." },

  // ── Z-Score Mini Glossary ──
  "z.intra":                   { en: "z_intra",                             es: "z_intra" },
  "z.intraDesc":               { en: "How unusual the symbol is vs its",    es: "Que tan raro esta el simbolo vs su" },
  "z.intraEmphasis":           { en: "own history",                         es: "propia historia" },
  "z.intraWindow":             { en: "(252d).",                             es: "(252d)." },
  "z.cross":                   { en: "z_cross",                             es: "z_cross" },
  "z.crossDesc":               { en: "How unusual it is vs the",            es: "Que tan raro esta vs el" },
  "z.crossEmphasis":           { en: "rest of the universe TODAY",          es: "resto del universo HOY" },
  "z.crossEnd":                { en: ".",                                   es: "." },
  "z.ofz":                     { en: "z_of_z ★",                           es: "z_of_z ★" },
  "z.ofzDesc":                 { en: "The",                                 es: "La" },
  "z.ofzEmphasis":             { en: "rarity of the rarity",               es: "rareza de la rareza" },
  "z.ofzEnd":                  { en: ": anomaly within anomaly.",           es: ": anomalia dentro de anomalia." },

  "hero.source":               { en: "source:",                             es: "fuente:" },
  "hero.refreshNote":          { en: "· refreshed 1×/day · click the",      es: "· refrescado 1×/dia · clic en el" },
  "hero.refreshEnd":           { en: "on each card for details",            es: "de cada card para mas detalle" },

  // ── Advanced Analytics Table Section ──
  "table.title":               { en: "raw table · multi-metric",            es: "tabla cruda · multi-metrica" },
  "table.desc":                { en: "Same data served from the",            es: "La misma data servida desde el endpoint" },
  "table.descEnd":             { en: "endpoint, with free metric selector and all three z-score layers (intra / cross / of_z).", es: ", con selector libre de metrica y las tres capas de z-score (intra / cross / of_z)." },
  "table.footer":              { en: "gold layer · bigquery · financial_marts.fact_derived_metrics · refreshed 1×/day", es: "gold layer · bigquery · financial_marts.fact_derived_metrics · refrescado 1×/dia" },

  // ── AdvancedAnalytics Component ──
  "aa.title":                  { en: "Advanced Analytics",                   es: "Analiticas Avanzadas" },
  "aa.subtitle":               { en: "Outlier Detector · Gold Layer (BigQuery)", es: "Detector de Outliers · Gold Layer (BigQuery)" },
  "aa.metricLabel":            { en: "metric",                               es: "metrica" },
  "aa.topN":                   { en: "Top-10 symbols with the",              es: "Top-10 simbolos con la" },
  "aa.topNBold":               { en: "most extreme anomaly",                 es: "anomalia mas extrema" },
  "aa.topNEnd":                { en: "of the day for",                       es: "del dia para" },
  "aa.topNSort":               { en: "Sorted by",                            es: "Ordenados por" },
  "aa.topNZDesc":              { en: "— z-score of the z-score: how unusual is this symbol's rarity vs the typical rarity of the universe TODAY.", es: "— z-score del z-score: que tan rara es la rareza de este simbolo vs la rareza tipica del universo HOY." },
  "aa.topNSource":             { en: "Data from",                            es: "Datos servidos desde" },
  "aa.loading":                { en: "loading",                              es: "cargando" },
  "aa.results":                { en: "results",                              es: "resultados" },
  "aa.symbol":                 { en: "Symbol",                               es: "Simbolo" },
  "aa.sector":                 { en: "Sector",                               es: "Sector" },
  "aa.tier":                   { en: "Tier",                                 es: "Tier" },
  "aa.noOutliers":             { en: "No outliers exceeding the threshold today.", es: "Sin outliers que superen el umbral hoy." },

  // ── Metric Select Labels ──
  "metric.rsi_14":             { en: "RSI 14",                              es: "RSI 14" },
  "metric.vol_1m":             { en: "Volatility 1M",                       es: "Volatilidad 1M" },
  "metric.vol_3m":             { en: "Volatility 3M",                       es: "Volatilidad 3M" },
  "metric.ret_1d":             { en: "Return 1D",                           es: "Retorno 1D" },
  "metric.ret_1m":             { en: "Return 1M",                           es: "Retorno 1M" },
  "metric.sma_50_gap":         { en: "Gap SMA 50",                          es: "Gap SMA 50" },
  "metric.sma_200_gap":        { en: "Gap SMA 200",                         es: "Gap SMA 200" },
  "metric.range_intraday":     { en: "Intraday Range",                      es: "Rango intradia" },
  "metric.high_dist_1y":       { en: "Dist. from 1Y High",                  es: "Dist. maximo 1Y" },

  // ── Metric Help Texts ──
  "metricHelp.rsi_14":         { en: "Wilder Relative Strength Index. >70 overbought, <30 oversold.", es: "Indice de fuerza relativa Wilder. >70 sobrecomprado, <30 sobrevendido." },
  "metricHelp.vol_1m":         { en: "Annualized log-return volatility over the last 21 trading days.", es: "Volatilidad anualizada de log-returns sobre los ultimos 21 dias habiles." },
  "metricHelp.vol_3m":         { en: "Annualized volatility over the last 63 trading days.", es: "Volatilidad anualizada sobre los ultimos 63 dias habiles." },
  "metricHelp.ret_1d":         { en: "Percentage change over the last day.", es: "Variacion porcentual ultimo dia." },
  "metricHelp.ret_1m":         { en: "Percentage change over the last 21 trading days.", es: "Variacion porcentual ultimos 21 dias habiles." },
  "metricHelp.sma_50_gap":     { en: "(close - SMA50) / SMA50. Positive = trading above the 50d average.", es: "(close - SMA50) / SMA50. Positivo = cotiza arriba del promedio 50d." },
  "metricHelp.sma_200_gap":    { en: "(close - SMA200) / SMA200. Positive = above the 200d average (bull).", es: "(close - SMA200) / SMA200. Positivo = arriba del promedio 200d (bull)." },
  "metricHelp.range_intraday": { en: "(high - low) / close. Measures session amplitude.", es: "(high - low) / close. Mide la amplitud de la sesion." },
  "metricHelp.high_dist_1y":   { en: "(close - max_1y) / max_1y. 0 = new 52-week high.", es: "(close - max_1y) / max_1y. 0 = nuevo maximo de 52 semanas." },

  // ── Glossary: Performance ──
  "glossary.perf.category":    { en: "Price change across specific timeframes. Measures trend direction and velocity. The baseline metric for historical returns, often compared against market benchmarks to determine relative strength.", es: "Cambio de precio en distintos plazos. Mide dirección y velocidad de tendencia. Métrica base para retornos históricos, generalmente comparada contra benchmarks del mercado." },
  "glossary.perf.ret_1d":      { en: "Price change over the last 1 day — how much the stock moved today compared to yesterday's close.", es: "Cambio de precio en el último día — cuánto se movió la acción hoy respecto al cierre de ayer." },
  "glossary.perf.ret_1w":      { en: "Price change over the last week (5 trading days). How much the stock moved over the past few days.", es: "Cambio de precio en la última semana (5 ruedas). Cuánto se movió la acción en los últimos días." },
  "glossary.perf.ret_1m":      { en: "Price change over the last month (about 21 trading days). A common short-term gauge.", es: "Cambio de precio en el último mes (~21 ruedas). Indicador estándar de corto plazo." },
  "glossary.perf.ret_3m":      { en: "Price change over the last 3 months. A standard benchmark for short-term momentum.", es: "Cambio de precio en los últimos 3 meses. Benchmark estándar de momentum." },
  "glossary.perf.ret_6m":      { en: "Price change over the last 6 months. Smooths out short-term noise.", es: "Cambio de precio en los últimos 6 meses. Suaviza el ruido de corto plazo." },
  "glossary.perf.ret_1y":      { en: "Price change over the last year (about 252 trading days). The textbook yardstick for long-term performance.", es: "Cambio de precio en el último año (~252 ruedas). La vara estándar para rendimiento de largo plazo." },

  // ── Glossary: Volatility ──
  "glossary.vol.category":     { en: "The magnitude of price swings, regardless of direction. It defines risk: low is stable, high is erratic. The core financial metric for risk modeling and option pricing.", es: "Magnitud de las oscilaciones de precio, sin importar dirección. Define el riesgo: bajo = estable, alto = errático. Métrica financiera central para modelado de riesgo y pricing de opciones." },
  "glossary.vol.range":        { en: "How wide today's price range is. Calculated as today's high minus today's low, divided by today's close. A busy, choppy day produces a wider range.", es: "Qué tan amplio es el rango de precio de hoy. Se calcula como máximo − mínimo, dividido por el cierre. Un día agitado produce un rango más amplio." },
  "glossary.vol.1w":           { en: "Volatility over the last week. Roughly: how much the daily price has been bouncing around recently. A higher number = more daily movement.", es: "Volatilidad de la última semana. Cuánto ha estado rebotando el precio diario. Mayor número = más movimiento diario." },
  "glossary.vol.1m":           { en: "Volatility over the last month. A short-term view of how 'wild' the stock has been.", es: "Volatilidad del último mes. Vista de corto plazo de qué tan 'salvaje' ha estado la acción." },
  "glossary.vol.3m":           { en: "Volatility over the last 3 months. A medium-term view of price swings.", es: "Volatilidad de los últimos 3 meses. Vista de mediano plazo de las oscilaciones." },
  "glossary.vol.6m":           { en: "Volatility over the last 6 months. Smoother — short spikes get averaged out.", es: "Volatilidad de los últimos 6 meses. Más suave — los picos cortos se promedian." },
  "glossary.vol.1y":           { en: "Volatility over the last year. The textbook standard for measuring how risky a stock is.", es: "Volatilidad del último año. El estándar de libro para medir el riesgo de una acción." },

  // ── Glossary: Momentum ──
  "glossary.mom.category":     { en: "Evaluates the speed and strength of price trends to spot continuations or reversals. Uses moving averages and oscillators to identify overbought/oversold conditions and time market entries.", es: "Evalúa la velocidad y fuerza de las tendencias para detectar continuaciones o reversiones. Usa promedios móviles y osciladores para identificar condiciones de sobrecompra/sobreventa." },
  "glossary.mom.rsi_14":       { en: "RSI = Relative Strength Index. A score from 0 to 100 that summarizes recent momentum, based on the last 14 trading-sessions. Above 70 = the stock has been rallying hard (might pull back). Below 30 = it has been falling hard (might bounce). The most popular momentum indicator in technical analysis.", es: "RSI = Índice de Fuerza Relativa. Puntaje de 0 a 100 que resume el momentum reciente en las últimas 14 ruedas. Arriba de 70 = rally fuerte (podría retroceder). Debajo de 30 = caída fuerte (podría rebotar). El indicador de momentum más popular del análisis técnico." },
  "glossary.mom.sma_20_gap":   { en: "How far the current price is above or below its average over the last 20 trading-sessions. Positive = above the average; negative = below. A short-term trend signal.", es: "Qué tan lejos está el precio actual de su promedio de las últimas 20 ruedas. Positivo = arriba del promedio; negativo = debajo. Señal de tendencia de corto plazo." },
  "glossary.mom.sma_50_gap":   { en: "How far the current price is above or below its average over the last 50 trading-sessions. A mid-term trend signal — traders often watch this level as support or resistance.", es: "Qué tan lejos está el precio de su promedio de 50 ruedas. Señal de tendencia de mediano plazo — los traders suelen mirar este nivel como soporte o resistencia." },
  "glossary.mom.sma_200_gap":  { en: "How far the current price is above or below its average over the last 200 trading-sessions. THE long-term trend line. Above zero is generally considered bull market territory; below zero, bear market territory.", es: "Qué tan lejos está el precio de su promedio de 200 ruedas. LA línea de tendencia de largo plazo. Arriba de cero = territorio alcista; debajo de cero = territorio bajista." },
  "glossary.mom.high_dist_1m": { en: "How far the current price is below its highest point of the last month. 0% means the price is right at the monthly peak; -5% means it is 5% below it.", es: "Qué tan lejos está el precio del máximo del último mes. 0% = en el pico mensual; -5% = 5% por debajo." },
  "glossary.mom.high_dist_1y": { en: "How far the current price is below its highest point of the last year (52-week). 0% means a brand-new yearly high. The classic 'how close are we to the top?' metric.", es: "Qué tan lejos está el precio del máximo del último año (52 semanas). 0% = nuevo máximo anual. La clásica métrica de '¿qué tan cerca estamos del techo?'." },

  // ── Glossary: Live Feed ──
  "glossary.feed":             { en: "Real-time market transactions. Each row is an actual trade happening right now. If you see no activity, remember that traditional stock markets close at night and on weekends. To see the engine running at full speed right now, search for BTC (Bitcoin), which trades 24/7.", es: "Transacciones de mercado en tiempo real. Cada fila es una operación real sucediendo ahora. Si no ves actividad, recordá que los mercados tradicionales cierran de noche y los fines de semana. Para ver el motor a toda velocidad, buscá BTC (Bitcoin), que opera 24/7." },

  // ── Glossary: Fundamentals ──
  "glossary.fund.market_cap":  { en: "Market Cap = the total dollar value of the company. Calculated as: share price × number of shares. Tells you how big the company is — small, medium, large, or mega.", es: "Cap. de Mercado = valor total en dólares de la empresa. Se calcula como: precio × cantidad de acciones. Indica el tamaño de la compañía." },
  "glossary.fund.pe_ttm":      { en: "P/E = Price-to-Earnings ratio (trailing twelve months). The share price divided by the company's profit per share over the last year. Roughly: how many years of current profits the stock price represents. Lower can mean cheaper; higher can mean investors expect strong growth.", es: "P/E = Ratio Precio/Ganancia (últimos 12 meses). El precio dividido por la ganancia por acción del último año. Cuántos años de ganancias actuales representa el precio. Más bajo = potencialmente barato; más alto = los inversores esperan crecimiento." },
  "glossary.fund.eps_ttm":     { en: "EPS = Earnings Per Share (trailing twelve months). The company's profit divided by the number of shares. How much each share earned over the past year.", es: "EPS = Ganancia por Acción (últimos 12 meses). La ganancia de la empresa dividida por la cantidad de acciones. Cuánto ganó cada acción en el último año." },
  "glossary.fund.shares":      { en: "The total number of shares the company has issued and that are currently held by investors. Used to calculate market cap and EPS.", es: "Cantidad total de acciones emitidas por la empresa y en manos de inversores. Se usa para calcular capitalización y EPS." },
  "glossary.fund.sector":      { en: "The broad industry group the company operates in (Technology, Healthcare, Energy, etc.). Useful for comparing it to similar companies.", es: "El grupo industrial amplio en el que opera la empresa (Tecnología, Salud, Energía, etc.). Útil para comparar con empresas similares." },
  "glossary.fund.industry":    { en: "A more specific sub-category within the sector (Software, Biotech, Oil & Gas, etc.). More precise than sector.", es: "Sub-categoría más específica dentro del sector (Software, Biotech, Oil & Gas, etc.). Más precisa que el sector." },
} as const;

export type TKey = keyof typeof dict;

// ── Context ──

interface I18nContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: TKey) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function getInitialLang(): Lang {
  try {
    const stored = localStorage.getItem("lang");
    if (stored === "es" || stored === "en") return stored;
  } catch { /* SSR or privacy mode */ }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(getInitialLang);

  const setLang = useCallback((newLang: Lang) => {
    setLangState(newLang);
    try { localStorage.setItem("lang", newLang); } catch { /* noop */ }
    document.documentElement.lang = newLang;
  }, []);

  const t = useCallback((key: TKey): string => {
    const entry = dict[key];
    if (!entry) return key;
    return entry[lang];
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
