// ──────────────────────────────────────────────────────────────────────────────
// FRONT-012 (PL_02): Metrics glossary — plain-English definitions.
//
// Single source of truth for every label rendered in MetricsGrid + FundamentalsBar.
// Texts are in simple English, jargon-light, written for non-traders (recruiters,
// CTOs, general public). Every item — even the obvious ones — has its own text,
// because tooltips are about confidence, not just information.
//
// Tone reference: imagine explaining to a smart friend who has never opened a
// brokerage account. No "annualized standard deviation". No "log returns".
//
// Naming convention: keys match backend field names exactly so a future runtime
// sanity check can compare `Object.keys(MOMENTUM_GLOSSARY)` against the API
// response shape.
// ──────────────────────────────────────────────────────────────────────────────

export const PERFORMANCE_GLOSSARY = {
  category:
    "Price change across specific timeframes. Measures trend direction and velocity. The baseline metric for historical returns, often compared against market benchmarks to determine relative strength.",
  ret_1d:
    "Price change over the last 1 day — how much the stock moved today compared to yesterday's close.",
  ret_1w:
    "Price change over the last 1 week (5 trading days). How much the stock moved over the past few days.",
  ret_1m:
    "Price change over the last 1 month (about 21 trading days). A common short-term gauge.",
  ret_3m:
    "Price change over the last 3 months. A standard benchmark for short-term momentum.",
  ret_6m:
    "Price change over the last 6 months. Smooths out short-term noise.",
  ret_1y:
    "Price change over the last 1 year (about 252 trading days). The textbook yardstick for long-term performance.",
} as const;

export const VOLATILITY_GLOSSARY = {
  category:
    "The magnitude of price swings, regardless of direction. It defines risk: low is stable, high is erratic. The core financial metric for risk modeling and option pricing.",
  range_intraday:
    "How wide today's price range is. Calculated as today's high minus today's low, divided by today's close. A busy, choppy day produces a wider range.",
  vol_1w:
    "Volatility over the last 1 week. Roughly: how much the daily price has been bouncing around recently. A higher number = more daily movement.",
  vol_1m:
    "Volatility over the last 1 month. A short-term view of how 'wild' the stock has been.",
  vol_3m:
    "Volatility over the last 3 months. A medium-term view of price swings.",
  vol_6m:
    "Volatility over the last 6 months. Smoother — short spikes get averaged out.",
  vol_1y:
    "Volatility over the last 1 year. The textbook standard for measuring how risky a stock is.",
} as const;

export const MOMENTUM_GLOSSARY = {
  category:
    "Evaluates the speed and strength of price trends to spot continuations or reversals. Uses moving averages and oscillators to identify overbought/oversold conditions and time market entries.",
  rsi_14:
    "RSI = Relative Strength Index. A score from 0 to 100 that summarizes recent momentum, based on the last 14 days. Above 70 = the stock has been rallying hard (might pull back). Below 30 = it has been falling hard (might bounce). The most popular momentum indicator in technical analysis.",
  sma_20_gap:
    "How far the current price is above or below its average over the last 20 days. Positive = above the average; negative = below. A short-term trend signal.",
  sma_50_gap:
    "How far the current price is above or below its average over the last 50 days. A mid-term trend signal — traders often watch this level as support or resistance.",
  sma_200_gap:
    "How far the current price is above or below its average over the last 200 days. THE long-term trend line. Above zero is generally considered bull market territory; below zero, bear market territory.",
  high_dist_1m:
    "How far the current price is below its highest point of the last month. 0% means the price is right at the monthly peak; -5% means it is 5% below it.",
  high_dist_1y:
    "How far the current price is below its 52-week high (highest price of the last year). 0% means a brand-new yearly high. The classic 'how close are we to the top?' metric.",
} as const;

export const LIVE_FEED_GLOSSARY = {
  description:
    "Real-time stream of price ticks coming directly from the exchange. Each row shows the timestamp, the trade price, and the change versus the previous tick (green = up, red = down). New ticks slide in at the top of the list. The pulsing green dot means the WebSocket connection is live and data is flowing.",
} as const;

export const FUNDAMENTALS_GLOSSARY = {
  market_cap:
    "Market Cap = the total dollar value of the company. Calculated as: share price × number of shares. Tells you how big the company is — small, medium, large, or mega.",
  pe_ttm:
    "P/E = Price-to-Earnings ratio (trailing twelve months). The share price divided by the company's profit per share over the last year. Roughly: how many years of current profits the stock price represents. Lower can mean cheaper; higher can mean investors expect strong growth.",
  eps_ttm:
    "EPS = Earnings Per Share (trailing twelve months). The company's profit divided by the number of shares. How much each share earned over the past year.",
  shares_outstanding:
    "The total number of shares the company has issued and that are currently held by investors. Used to calculate market cap and EPS.",
  sector:
    "The broad industry group the company operates in (Technology, Healthcare, Energy, etc.). Useful for comparing it to similar companies.",
  industry:
    "A more specific sub-category within the sector (Software, Biotech, Oil & Gas, etc.). More precise than sector.",
} as const;
