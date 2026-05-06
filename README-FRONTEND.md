# README-FRONTEND · React 19 + Vite 8 + Tailwind 4 — Bloomberg Terminal on acid

Documentación técnica del cliente: SPA en React 19 que consume el WebSocket
`/ws/live/{symbol}` y los REST `/symbols`, `/analytics/anomalies` del backend
FastAPI descrito en `README.md` y `README-INGEST.md`.

**Fuera de scope:** ingesta de datos, batch ETL, DBT, BigQuery — esos viven en
los otros dos READMEs. Acá hablamos solo del cliente.

**Live:** [leonardovila.com/financial](https://leonardovila.com/financial/)

---

## 1. Stack y decisiones de base

| Pieza                  | Versión          | Por qué está acá                                                                 |
|------------------------|------------------|----------------------------------------------------------------------------------|
| **React**              | 19.2             | `useEffect` con cleanup en cada subscriber WS + StrictMode tolerante.            |
| **TypeScript**         | 5.9 (strict)     | Discriminated unions sobre el WS protocol — el tipado paga por sí solo.          |
| **Vite**               | 8.0              | Dev proxy para REST + WS, HMR, build estático. Sin SSR (no se necesita).         |
| **Tailwind**           | 4.2 (CSS-first)  | `@theme` block en `index.css` — sin `tailwind.config.js`. Tokens como CSS vars.  |
| **Zustand**            | 5.0              | Store WS centralizado sin boilerplate. Vanilla JS subscribe API para Chart.      |
| **lightweight-charts** | 5.1              | TradingView open-source. Una vez creado, se actualiza con `update()` O(1).       |
| **react-router**       | NO INSTALADO     | Dos rutas → mini-router en `App.tsx` por `window.location.pathname`. 5 LOC.      |

No hay React Query, ni Redux Toolkit, ni Context API global, ni Radix, ni
component library. Es deliberado: cada feature elegida cuesta su peso en
bundle y en tiempo de aprendizaje del próximo dev.

---

## 2. Layout del proyecto

```
frontend/
├── Dockerfile                # multi-stage: node 20 build → nginx alpine
├── index.html                # Meta tags OG + JetBrains Mono preload
├── vite.config.ts            # base='/financial/', dev proxy a :8000
├── tsconfig.{app,node}.json  # strict + noUnused* + verbatimModuleSyntax
├── eslint.config.js          # tseslint + react-hooks + react-refresh
├── .env.development          # VITE_API_URL=http://localhost:8000
├── .env.production           # VITE_API_URL=https://api.leonardovila.com
├── public/
│   ├── favicon.svg
│   └── og-image.png          # 3840×1808, referenciada en meta og:image
└── src/
    ├── main.tsx              # createRoot + <StrictMode>
    ├── App.tsx               # mini-router (5 LOC)
    ├── index.css             # @theme + animations + scrollbar styling
    │
    ├── layouts/
    │   ├── Dashboard.tsx                # ruta /financial/
    │   └── AdvancedAnalyticsPage.tsx    # ruta /financial/avanzadas
    │
    ├── components/
    │   ├── SymbolSearch.tsx       # search bar + dropdown + price preview
    │   ├── FundamentalsBar.tsx    # ticker tape: Mkt Cap, P/E, EPS, ...
    │   ├── Chart.tsx              # candles + volume (lightweight-charts)
    │   ├── TickStack.tsx          # live tick feed (sidebar desktop / mobile)
    │   ├── MetricsGrid.tsx        # Performance / Volatility / Momentum
    │   ├── MetricCard.tsx         # row con flash green/red on change
    │   ├── StatusBar.tsx          # connection dot + tick count + age
    │   ├── InfoTooltip.tsx        # popover viewport-aware, sin libs
    │   ├── RankingBoard.tsx       # podio top-3 outliers por métrica
    │   └── AdvancedAnalytics.tsx  # tabla densa multi-métrica + select
    │
    ├── stores/
    │   └── wsStore.ts             # Zustand: WS lifecycle + state slices
    │
    ├── lib/
    │   ├── theme.ts               # paleta + opciones del chart
    │   ├── formatters.ts          # currency/percent/number/timestamp
    │   └── glossary.ts            # textos del InfoTooltip (single source)
    │
    └── types/
        └── ws.ts                  # discriminated union del WS protocol
```

---

## 3. Routing — el mini-router de 5 líneas

```tsx
// src/App.tsx
const path = window.location.pathname.replace(/\/+$/, "");
if (path === "/financial/avanzadas") return <AdvancedAnalyticsPage />;
return <Dashboard />;
```

| Path                         | Layout                     | Qué muestra                                                                  |
|------------------------------|----------------------------|------------------------------------------------------------------------------|
| `/financial/` (default)      | `Dashboard`                | Chart + ticks en vivo + metrics grid + fundamentals bar                      |
| `/financial/avanzadas`       | `AdvancedAnalyticsPage`    | 9 ranking boards (BigQuery) + tabla densa multi-métrica                      |

**Por qué no react-router:** dos rutas estáticas, navegación con `<a href>`
nativo (sin link interceptor), refresco completo aceptable. Agregar la
dependencia sumaría ~12kB gzipped y un provider para nada.

**`base: '/financial/'`** en `vite.config.ts` es lo que permite que el SPA
viva bajo ese prefijo en el dominio principal: Vite reescribe los paths de
los assets (`/financial/assets/index-xyz.js`) y nginx hace `try_files $uri
$uri/ /financial/index.html` para SPA fallback.

---

## 4. State management — Zustand, narrow selectors, subscribe API

### 4.1 Por qué Zustand y no Context o Redux

- **Context API:** un cambio en cualquier slice re-rendea TODOS los
  consumidores del provider. Para un stream de ticks (1-N veces por segundo)
  eso es prohibitivo.
- **Redux Toolkit:** boilerplate desproporcionado para una app de dos rutas.
- **Zustand:** un único `create()` con setters arbitrarios. Soporta selectores
  con shallow comparison (`useStore(s => s.foo)`) que solo re-rendean cuando
  el slice cambia. Y, crítico, expone el método **`subscribe(fn)` vanilla**:
  un componente puede escuchar cambios SIN re-renderear. Lo usa `Chart.tsx`
  para pasar datos a lightweight-charts via setters imperativos sin entrar
  en el render cycle de React.

### 4.2 Shape del store

```ts
// src/stores/wsStore.ts (resumido)
interface WsState {
  // Connection
  socket: WebSocket | null;
  status: "disconnected" | "connecting" | "connected" | "reconnecting";
  connectionError: string | null;

  // Symbol
  currentSymbol: string;
  companyName: string | null;
  pendingSymbolDisplay: string | null;   // "AAPL — Apple Inc" durante el switch

  // Data
  seedData: SeedPayload | null;          // 1× por símbolo: chart_candles, fundamentals, metrics iniciales
  latestTick: TickPayload | null;        // último tick recibido
  tickHistory: TickPayload[];            // ring buffer (50 desktop / 20 mobile)
  fundamentals: FundamentalsData | null;
  metrics: AllMetrics;

  // Derived
  isMarketOpen: boolean;                 // false si llega heartbeat (mercado cerrado)

  // Actions
  connect: (symbol: string) => void;
  disconnect: () => void;
  switchSymbol: (newSymbol: string, displayName?: string | null) => void;
}
```

### 4.3 Selectores narrow — patrón canónico

Todo componente extrae **solo el slice que necesita**. Ejemplo:

```tsx
// FundamentalsBar.tsx — solo se re-rendea si fundamentals cambia.
const fundamentals = useWsStore((s) => s.fundamentals);

// SymbolSearch.tsx — múltiples selectores narrow, no un único objeto.
const currentSymbol = useWsStore((s) => s.currentSymbol);
const companyName   = useWsStore((s) => s.companyName);
const livePrice     = useWsStore((s) => s.latestTick?.candle.close ?? null);
```

Lo opuesto (`const state = useWsStore()`) generaría un re-render por cada
mutación del store, incluso de slices que el componente no mira.

### 4.4 Suscripción imperativa para Chart

```tsx
// Chart.tsx — escucha cambios sin entrar al render cycle de React.
useEffect(() => {
  const unsub = useWsStore.subscribe((state, prev) => {
    if (state.seedData !== prev.seedData)   { /* setData()  */ }
    if (state.latestTick !== prev.latestTick) { /* update() */ }
  });
  return unsub;
}, []);
```

El chart se crea **una vez** en el primer `useEffect([])` y se mantiene vivo
hasta el unmount. Los cambios de símbolo NO destruyen el chart: solo
disparan `series.setData([...nuevasVelas])`. Los ticks live disparan
`series.update(unaVelaSola)` (O(1) en lightweight-charts).

---

## 5. WebSocket lifecycle — el corazón del Dashboard

### 5.1 Flujo de conexión

```
mount Dashboard ─► connect("BTC")
                      │
                      ▼
                  new WebSocket(`${WS_BASE}/ws/live/BTC`)
                      │
                      ▼
                  ws.onopen ─► status="connected", reconnectAttempt=0
                      │
                      ▼
                  ws.onmessage ─► JSON.parse ─► switch(msg.type)
                      │
                      ├── "seed"             → guarda candles + fundamentals + metrics iniciales
                      ├── "tick"             → empuja a tickHistory (ring buffer), actualiza metrics
                      ├── "company_name"     → patch del nombre comercial
                      ├── "fundamentals"     → patch del bloque fundamentals
                      ├── "heartbeat"        → mercado cerrado (isMarketOpen=false)
                      ├── "idle_warning"     → server avisa que vamos camino al kick → cliente manda {action:"ping"}
                      ├── "idle_disconnect"  → server cerró por inactividad → reconnect si pestaña visible
                      ├── "session_expired"  → TTL de 2h llegó al límite → reconnect inmediato
                      └── "error"            → connectionError (UI muestra mensaje)
```

### 5.2 Reconnect con backoff exponencial + visibility API

```ts
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS  = 16000;
// 1s → 2s → 4s → 8s → 16s → 16s → ...
delay = min(BASE * 2 ** attempt, MAX);
```

**Visibility API:** si la pestaña está oculta (`document.visibilityState ===
"hidden"`), NO reconectamos. Guardamos `pendingReconnectSymbol` y disparamos
el `connect()` cuando vuelve `visibilitychange → visible`. En mobile esto
salva batería: pasar a otra app no re-abre el WS hasta que el usuario
vuelva.

**Códigos de cierre tratados aparte:**

| Code | Acción                                                       |
|------|--------------------------------------------------------------|
| 1000 | Cierre normal (nuestro `disconnect()`) — no reconectar.      |
| 4001 / 4003 / 4029 | Rechazo de seguridad/capacidad — no reconectar, mostrar `connectionError`. |
| otros | Cierre inesperado — reconectar con backoff.                 |

### 5.3 Switch de símbolo sin reabrir socket

```ts
// switchSymbol() — el socket sigue abierto, mandamos la orden.
ws.send(JSON.stringify({ action: "switch", symbol: "TSLA" }));

// Mientras tanto, en el cliente: pendingSymbolDisplay = "TSLA — Tesla Inc"
// y seedData=null (transition lock — ver §5.4).
```

El header (`SymbolSearch`) muestra el `pendingSymbolDisplay` con `animate-pulse`
hasta que llega el nuevo `seed`. Cero re-conexión. Cero glitch.

### 5.4 Transition lock — bug que no es bug

Cuando se cambia de símbolo, el server puede estar en medio de mandar un
último tick del símbolo anterior. Si llegara después del `switch`, el
chart pintaría una vela rara fuera de rango.

**Defensa explícita:**
```ts
case "tick": {
  if (!get().seedData) return;   // drop ticks hasta que arribe el seed nuevo
  // ...
}
```

`switchSymbol()` setea `seedData=null` antes de mandar la orden. Cualquier
tick que llegue antes del nuevo seed se descarta.

### 5.5 Mobile-aware tick history cap

```ts
const IS_TOUCH = navigator.maxTouchPoints > 0;
const TICK_HISTORY_CAP = IS_TOUCH ? 20 : 50;
```

Menos memoria, menos paint en devices baratos. El array se mantiene
ordenado por timestamp descendente, con `slice(0, CAP)` después de cada
tick. No hay `Array.shift` (O(n)): es `[nuevo, ...prev].slice(0, CAP)`.

---

## 6. Componentes — guía rápida de re-render y responsabilidad

### 6.1 `Dashboard.tsx` (layout)

CSS Grid de 6 filas (mobile) / 5 filas + 2 columnas (desktop ≥1024px).
Mobile-first: las clases base son móviles, los breakpoints `sm:` `lg:` `xl:`
solo agregan/sobreescriben.

Filas:
1. Bridge link a leonardovila.com (back home).
2. Big CTA neón al `/financial/avanzadas`.
3. `SymbolSearch` (header bar).
4. `FundamentalsBar` (ticker tape de Mkt Cap, P/E, ...).
5. `Chart` + (en desktop) `TickStackSidebar`.
6. `TickStackMobile` (oculto en desktop) + `MetricsGrid` + `StatusBar`.

`Dashboard` solo llama `connect("BTC")` en `useEffect([])` y `disconnect()`
en cleanup. El resto es composición.

### 6.2 `Chart.tsx`

Wrapper sobre lightweight-charts v5. Reglas:
- **Una sola instancia.** `createChart(el, { autoSize: true })` en mount,
  `chart.remove()` en unmount. Switch de símbolo → `setData()` no `remove()`.
- **`autoSize: true`** delega el ResizeObserver a la lib (LWC lo maneja
  internamente desde la v4). Cero código nuestro de resize/orientation.
- **Sanitización de seed candles:** dedupe por timestamp con `Map`, sort
  ascendente. Si la API devolviera duplicados, LWC lanza assertion error.
- **Empty seed:** si `chart_candles.length === 0`, llamamos `setData([])`
  para limpiar el canvas — si no, queda mostrando las velas del símbolo
  anterior.
- **Crosshair sin label horizontal en touch:** evita que se tape el precio
  con el dedo.

### 6.3 `TickStack.tsx` (sidebar + mobile)

Dos componentes exportados (`TickStackSidebar`, `TickStackMobile`) que
comparten una `TickList` interna. Cada `TickRow` es `React.memo` con
`prevClose` calculada desde el siguiente índice del array — el delta se
muestra coloreado con `signClass()`.

Animación `slideIn` (150ms) **solo en la fila más nueva** (`isFirst={i===0}`).
Las viejas no re-renderean (memo) y por tanto no animan.

Empty state: card con CTA explícito a buscar `BTC` (24/7 = siempre live,
útil cuando NYSE/NASDAQ están cerrados).

### 6.4 `MetricsGrid.tsx` + `MetricCard.tsx`

Tres tarjetas: Performance / Volatility / Momentum.

Desktop ≥640px: `grid-cols-3`. Mobile <640px: `flex overflow-x-auto
snap-x snap-mandatory` + tab bar arriba.

**Sync de tabs con scroll-snap (mobile):** `IntersectionObserver` con
`threshold: 0.6` observa cada card; cuando una entra al viewport, actualiza
`activeTab`. Tap en una tab → `card.scrollIntoView({ behavior: "smooth" })`.
No hay state ambiguo: el scroll y los tabs siempre coinciden.

**Flash green/red on change** — `MetricCard` mantiene `prevRef` con el valor
anterior, compara contra el nuevo, agrega `flash-green` o `flash-red`
(animación de 300ms en `index.css`) y la quita con `setTimeout`.

### 6.5 `FundamentalsBar.tsx`

Horizontal ticker tape. Desktop: 6 ítems en fila sin scroll. Mobile:
`overflow-x-auto` con `scroll-fade-right` (gradiente lineal CSS al final
del contenedor) que sugiere visualmente que hay más contenido.

`scroll-fade-right` está definido en `index.css` con `::after` y
`pointer-events: none` para no bloquear el scroll.

### 6.6 `SymbolSearch.tsx`

Header bar con dos modos:
- **Idle:** muestra `[symbol] — [companyName]   $price`. Click activa.
- **Active:** input real con dropdown filtrado.

Estado interno: `query`, `highlighted` (índice resaltado para teclado),
`active`. La lista de símbolos viene de `GET /symbols` con `fetch` plano
en `useEffect([])` — no se cachea entre rutas porque el componente se
desmonta al cambiar a `/financial/avanzadas`.

Navegación por teclado: `ArrowDown` / `ArrowUp` mueven el highlight,
`Enter` selecciona, `Esc` cierra.

Click outside: `mousedown` listener en `document`, removido en cleanup.

`HighlightedSymbol` resalta en neón la subcadena buscada usando
`indexOf` case-insensitive — sin regex (más rápido para strings cortas).

### 6.7 `StatusBar.tsx`

Footer de altura fija. Tres bloques:
- Izquierda: dot coloreado + label (`LIVE`/`CONNECTING`/`OFFLINE`). Pulso
  CSS solo cuando status="connected".
- Centro: símbolo activo.
- Derecha: tick count + "Last: Xs ago".

El reloj relativo usa `setInterval(1000)` que se reseteta cada vez que llega
un nuevo `latestTick.ts`.

### 6.8 `InfoTooltip.tsx` — popover sin libs

~200 LOC, sin Radix, sin floating-ui. Decisión consciente: la app necesita
un popover y nada más. Bundle más chico, control total.

Cómo posiciona:
- **Horizontal:** centrado sobre el botón, clamped a `[8px, vp.w - width - 8px]`
  (nunca overflowea izq/der).
- **Vertical:** mide `spaceBelow` y `spaceAbove`. Prefiere abajo. Flippea
  arriba si abajo es muy chico Y arriba tiene más espacio. `maxHeight` se
  ajusta al espacio disponible y el popup tiene `overflow-y: auto`.

Cierre: click outside, `Escape`, scroll, resize. Los dos últimos cierran
porque el popup es `position: fixed` y se desincronizaría del botón si
algo se mueve.

Color amarillo (`#ffcc00`): el verde neón ya está sobrecargado (deltas
positivos, dot LIVE, candles up, search highlight). Amarillo = "info"
universal (Stack Overflow, Bootstrap).

### 6.9 `RankingBoard.tsx` (página avanzadas)

Card que muestra el podio top-3 para una métrica. Props clave:

```ts
interface RankingBoardProps {
  metric: string;                          // "rsi_14" | "vol_1m" | ...
  filter: "pos" | "neg" | "abs";           // signo del z_of_z
  accent: "neon" | "red" | "yellow" | "blue";  // color dominante
  formatMetric?: (v: number | null) => string;
  metricShort: string;                     // etiqueta tipográfica
}
```

Hace `fetch(/analytics/anomalies?metric=...&limit=20)`, filtra por signo del
`z_of_z` y rankea por `|z_of_z|` desc. El #1 se renderea con tipografía
~2× más grande que los demás (podio implícito).

`AbortController` no está implementado todavía: si el componente se
desmonta antes de la respuesta, hay un `cancelled` flag local. El fetch
sigue volando pero el `setState` se ignora — es suficiente para esta app
(no hay race conditions porque cada `RankingBoard` tiene `metric` fijo).

### 6.10 `AdvancedAnalytics.tsx`

Tabla densa multi-métrica. Select libre de métrica (RSI, vol_1m, ret_1d,
sma_50_gap, ...). Render de las tres capas de z-score (`z_intra`,
`z_cross`, `z_of_z`) coloreadas según magnitud:

```
|z| ≥ 2 → neón (positivo) o rojo (negativo)
1 ≤ |z| < 2 → amarillo
|z| < 1 → texto base
```

Columns hidden por viewport (`hidden md:table-cell`, `hidden lg:table-cell`)
para que la tabla no se rompa en mobile.

---

## 7. Tailwind 4 — CSS-first config

No hay `tailwind.config.js`. Toda la configuración vive en `src/index.css`:

```css
@import "tailwindcss";

@theme {
  --color-bg:     #0a0c18;
  --color-panel:  #131726;
  --color-border: #2d3450;
  --color-text:   #e6e8f0;
  --color-muted:  #7078a0;
  --color-neon:   #00ff00;
  --color-red:    #ff0044;
  --color-blue:   #0088ff;
  --color-yellow: #ffcc00;
  --font-mono:    "JetBrains Mono", "Roboto Mono", ...;
}
```

Esto registra `text-[var(--color-neon)]`, `bg-[var(--color-panel)]`, etc. en
el JIT de Tailwind. Si necesitamos un nuevo color, va al `@theme` y queda
disponible en todas las clases utility.

Animaciones custom (`flashGreen`, `flashRed`, `pulse`, `slideIn`) están
declaradas como `@keyframes` planos + clases CSS de uso (`.flash-green`,
etc.). Tailwind 4 las respeta.

Densidad responsive de la tipografía:

```css
html { font-size: 12px; }
@media (min-width: 641px)  { html { font-size: 13px; } }
@media (min-width: 1025px) { html { font-size: 14px; } }
```

Esto hace que `text-sm`, `text-xs`, etc. escalen sin tocar cada componente.

---

## 8. Build, dev, deploy

### 8.1 Dev local

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173, base path /financial/
```

`vite.config.ts` proxiea las llamadas REST y WS al backend en `:8000`:

```ts
server: {
  proxy: {
    '/symbols':       'http://localhost:8000',
    '/ohlcv':         'http://localhost:8000',
    '/fundamentals':  'http://localhost:8000',
    '/performance':   'http://localhost:8000',
    '/volatility':    'http://localhost:8000',
    '/volume':        'http://localhost:8000',
    '/analytics':     'http://localhost:8000',
    '/ws':            { target: 'http://localhost:8000', ws: true },
  },
}
```

Con esto el código del front nunca tiene URLs hardcodeadas con `localhost`:
todo va por path relativo y Vite redirige.

### 8.2 Variables de entorno (Vite)

Vite **inyecta las VITE_*** en build time, NO en runtime. La sustitución
ocurre en el bundle final, así que cambiar `.env.production` requiere
rebuild + redeploy.

```
.env.development:
  VITE_API_URL=http://localhost:8000
  VITE_WS_URL=ws://localhost:8000

.env.production:
  VITE_API_URL=https://api.leonardovila.com
  VITE_WS_URL=wss://api.leonardovila.com
```

Lectura en código:
```ts
const API_BASE = import.meta.env.VITE_API_URL ?? `${window.location.origin}`;
const WS_BASE  = import.meta.env.VITE_WS_URL  ?? `${proto}//${host}`;
```

El fallback al `window.location` es lo que permite que el build funcione
detrás de cualquier dominio sin envar variables — útil para preview deploys.

### 8.3 Build

```bash
npm run build   # tsc -b && vite build → frontend/dist/
```

`tsc -b` corre antes de Vite y falla el build si hay error de tipos: ningún
deploy puede pasar con TS errors. Vite emite assets versionados con hash
(`index-abc123.js`) en `dist/financial/`.

### 8.4 Producción — Nginx serving

`frontend/Dockerfile` es multi-stage:

```dockerfile
# Stage 1: build
FROM node:20-alpine AS build
COPY package*.json ./ && npm ci
COPY . . && npm run build

# Stage 2: serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html/financial
# config inline:
#   location /financial/ { try_files $uri $uri/ /financial/index.html; }
#   location ~* \.(js|css|png|jpg|svg|woff2?)$ {
#     expires 1y; add_header Cache-Control "public, immutable";
#   }
```

Nginx vs `vite preview` en prod: nginx ~5MB de RAM, node ~50MB+. Para
servir estáticos no hay debate.

En AWS (target), este contenedor desaparece y los assets se sirven desde
S3 + CloudFront (caching edge). El bundle es el mismo: solo cambia el
servidor.

---

## 9. Contrato con el backend

### 9.1 REST (consumo del front)

| Endpoint                                  | Componente que lo llama   | Cuándo                                    |
|-------------------------------------------|---------------------------|-------------------------------------------|
| `GET /symbols`                            | `SymbolSearch`            | mount del Dashboard                       |
| `GET /analytics/anomalies?metric=X&limit=20&min_abs_z=0.5` | `RankingBoard` (×9) | mount del AdvancedAnalyticsPage  |
| `GET /analytics/anomalies?metric=X&limit=10&min_abs_z=1.0` | `AdvancedAnalytics` | mount + cambio del select        |

Los `/ohlcv`, `/fundamentals`, `/performance`, `/volatility` están proxiados
en dev pero **el front no los llama directamente** — todos los datos del
dashboard llegan por el WebSocket. Quedan en el proxy para herramientas
externas (curl, Postman, otros clientes).

### 9.2 WebSocket — protocolo (cliente)

Ver `src/types/ws.ts` para la discriminated union completa.

**Cliente → Server:**
```json
{ "action": "switch", "symbol": "TSLA" }
{ "action": "ping" }
```

**Server → Cliente** (los 9 tipos que el cliente trata):
```json
{ "type": "seed",            "symbol": "AAPL", "chart_candles": [[ts,o,h,l,c,v], ...], "company_name": "Apple Inc", "fundamentals": {...}, "metrics": {...} }
{ "type": "tick",            "candle": { "ts":..., "open":..., ... }, "metrics": {...}, "ts": 1741... }
{ "type": "company_name",    "name": "Apple Inc" }
{ "type": "fundamentals",    "data": {...} }
{ "type": "heartbeat" }
{ "type": "idle_warning" }
{ "type": "idle_disconnect" }
{ "type": "session_expired" }
{ "type": "error",           "message": "Unknown symbol: ZZZ" }
{ "type": "pong" }
```

El switch en `wsStore.ts` es exhaustivo gracias al discriminated union — TS
fuerza a manejar cada `type`. Si el backend agrega uno nuevo (ej: `news`),
el compilador rompe el build hasta que lo tratemos.

### 9.3 Formato de candles

Dos formas según el origen — decisión del backend para ahorrar bytes en el
seed (que puede traer 4500 velas):

```ts
// Seed: tuple posicional [ts, o, h, l, c, v]
type SeedCandle = [number, number, number, number, number, number];

// Tick: dict explícito (una vela sola, no compensa el ahorro)
interface CandleDict { ts: number; open: number; high: number; low: number; close: number; volume: number; }
```

`Chart.tsx` tiene `seedToCandle()` y `tickToCandle()` para mapear ambos al
formato de lightweight-charts.

---

## 10. Performance — patrones aplicados y por qué

| Problema                                    | Solución                                                              | Dónde                                |
|---------------------------------------------|-----------------------------------------------------------------------|--------------------------------------|
| Re-render de toda la app por cada tick      | Selectores narrow de Zustand                                          | Cada componente                      |
| Re-render del chart cycle React             | `useWsStore.subscribe(fn)` imperativo                                 | `Chart.tsx`                          |
| Re-render de filas viejas del tick stack    | `React.memo` en `TickRow` con `key={tick.ts + "-" + tick.candle.ts}`  | `TickStack.tsx`                      |
| `Intl.NumberFormat` recreado en cada render | Singletons module-level                                               | `lib/formatters.ts`                  |
| Animación `slideIn` en filas viejas         | Solo `isFirst={i===0}` agrega la clase                                | `TickStack.tsx`                      |
| Tab sync vs scroll-snap                     | `IntersectionObserver` con `threshold: 0.6`                           | `MetricsGrid.tsx`                    |
| Grow `tickHistory` sin tope                 | Ring buffer con `slice(0, CAP)` después de cada push                  | `wsStore.ts`                         |
| Reconnect storms                            | Backoff exponencial 1→16s                                             | `wsStore.ts`                         |
| Reconnect mobile en background              | `document.visibilityState` gate                                       | `wsStore.ts`                         |

---

## 11. Mobile-first — qué cambia por viewport

| Breakpoint | px         | Cambios principales                                                                  |
|------------|------------|---------------------------------------------------------------------------------------|
| base       | < 640      | `font-size: 12px`. MetricsGrid en scroll-snap horizontal con tabs. Chart full-width. TickStackMobile (4 filas). |
| `sm:`      | ≥ 640      | `font-size: 13px`. MetricsGrid `grid-cols-3`. FundamentalsBar sin scroll.            |
| `lg:`      | ≥ 1024     | `font-size: 14px`. Dashboard pasa a 2 columnas (78fr/22fr). TickStackSidebar persistente. |
| `xl:`      | ≥ 1280     | Columnas 82fr/18fr (más aire al chart en monitores grandes).                          |

Touch targets: `--touch-min: 44px` en mobile, `28px` en desktop. Las filas
del tick feed son `h-9` mobile / `h-7` desktop.

`safe-area-inset-bottom` (iOS home indicator) aplicado al `StatusBar` y al
big CTA de `/financial/avanzadas`.

---

## 12. Conocido — gaps y decisiones diferidas

- **AbortController** en `RankingBoard` y `AdvancedAnalytics`: hoy se
  ignoran respuestas tardías con un flag local. Si tuviéramos que llamar
  endpoints más caros o más frecuentes, valdría la pena.
- **Test runner**: no hay Vitest todavía. La app es chica y la verificación
  manual + TypeScript estricto cubre. El primer test que hace falta es la
  exhaustividad del switch en `wsStore.ts` cuando el backend agregue un
  nuevo tipo de mensaje.
- **i18n**: hardcoded ES/EN mezclado en strings. Si crece, glossary.ts es
  el punto natural para extraer y volverlo función de locale.
- **Error boundary**: no hay. Un throw en un componente revienta toda la
  UI. Aceptable mientras la superficie sea esta.
- **Service worker / offline**: no se necesita — sin red no hay datos
  útiles que mostrar. Mantener el bundle chico es más prioritario.

---

## 13. Mapa de dependencias entre componentes y store

```
                       useWsStore (Zustand)
                              │
           ┌──────────────────┼──────────────────┬───────────────┐
           │                  │                  │               │
    SymbolSearch          Chart              TickStack       MetricsGrid
    (currentSymbol,    (subscribe — fuera   (tickHistory)   (metrics)
     companyName,       del render cycle)
     latestTick,
     switchSymbol)
           
           
    FundamentalsBar    StatusBar
    (fundamentals)     (status,
                        currentSymbol,
                        tickHistory,
                        latestTick.ts)
```

`AdvancedAnalyticsPage` no toca el store. Sus componentes (`RankingBoard`,
`AdvancedAnalytics`) hablan solo con el REST `/analytics/anomalies` —
viven en un mundo aparte de los datos en vivo.

---

## 14. Cómo correr el front aislado del backend

```bash
# 1. Dejar /symbols y /analytics apuntando al server real (api.leonardovila.com)
echo 'VITE_API_URL=https://api.leonardovila.com' > .env.development.local
echo 'VITE_WS_URL=wss://api.leonardovila.com'    >> .env.development.local

# 2. Arrancar Vite ignorando el proxy local
npm run dev

# 3. Abrir http://localhost:5173/financial/
```

Con eso podés iterar React contra el WS y la API de producción sin
levantar Postgres ni FastAPI localmente. Útil para PRs que solo tocan UI.

---

## 15. Cosas para señalar en una entrevista

1. **WS con StrictMode tolerante.** El `connect/disconnect` está en un
   `useEffect`, y la lógica del store maneja sockets duplicados (cierra el
   anterior antes de abrir el nuevo) — StrictMode mount/unmount/mount
   doble en dev no bugea.
2. **Transition lock.** Drop de ticks rezagados durante el switch de
   símbolo. Tres líneas de código que evitan velas zombi.
3. **Subscribe imperativo a Zustand.** El chart no entra al render cycle.
   1k ticks/min no causan presión sobre React.
4. **Mini-router de 5 LOC.** Decidí explícitamente no traer react-router.
   Recruiter pregunta "¿y si crece?" → respuesta lista: trade-off de bundle
   vs features que hoy no necesito. Cuando sume tres rutas más, lo migro.
5. **InfoTooltip viewport-aware.** Mostrar que se entendió `getBoundingClientRect`
   + `position: fixed` + flip vertical sin pegar a una lib.
6. **Discriminated union del WS protocol.** Ts forzando exhaustividad. Si
   alguien borra un `case` del switch en `wsStore.ts`, el compilador grita.
7. **Mobile-first real.** No es solo `min-width` breakpoints — hay
   IntersectionObserver para tabs, ring buffer reducido en touch, visibility
   API para reconnect.
8. **Tailwind 4 CSS-first.** Cero JS de config. Tokens del design system
   son CSS variables consumidas tanto por Tailwind como por
   `lightweight-charts` (`lib/theme.ts`). Una sola fuente de verdad.

---

Para el resto del sistema (ingesta, ETL, DBT, BigQuery, AWS) ver
[`README.md`](README.md) y [`README-INGEST.md`](README-INGEST.md).
