// Mini-router por pathname. No vale la pena meter react-router para 2 rutas.
// Vite base es '/financial/', asi que la pagina avanzada vive en
// '/financial/avanzadas'.

import Dashboard from "./layouts/Dashboard";
import AdvancedAnalyticsPage from "./layouts/AdvancedAnalyticsPage";

export default function App() {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/financial/avanzadas") {
    return <AdvancedAnalyticsPage />;
  }
  return <Dashboard />;
}
