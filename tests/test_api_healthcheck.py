"""
P0_02 Test 3 — FastAPI app imports cleanly + /health route is registered.

Why this test exists:
  When we reach Phase 2 (ECS Fargate + Application Load Balancer), the ALB
  target group polls a healthcheck endpoint to decide whether to route traffic
  to the container. Without a working `/health` endpoint, the ALB marks the
  target as unhealthy and never routes anything — classic "503 Service
  Unavailable in prod" debugging nightmare at 3am.

  This test locks two invariants:
    1. IMPORT SMOKE — the entire `financial_data_etl.api.app` module imports
       cleanly. That transitively validates live_compute, live_seed,
       live_session_manager, live_state, storage, and the TradingView asset
       catalog. If any of those imports are broken, this fails instantly.
    2. HEALTH ROUTE CONTRACT — GET /health is registered. When a future refactor
       accidentally removes or renames the route, this test explodes before
       the change reaches main, preventing an ALB outage on the next deploy.

  We intentionally do NOT use FastAPI's TestClient here: TestClient triggers
  the app's lifespan (which calls _ensure_schema() and hits PostgreSQL).
  Instead we inspect app.routes directly — faster, DB-free, CI-safe.
"""

from fastapi.routing import APIRoute


def test_api_app_imports_cleanly():
    """Transitively validates the entire API module import chain."""
    from financial_data_etl.api import app as app_module
    assert app_module.app is not None
    assert app_module.app.title == "financial-data-etl api"


def test_health_route_is_registered():
    """GET /health must exist and return a 200 path (ALB requirement)."""
    from financial_data_etl.api.app import app

    health_routes = [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/health"
    ]
    assert len(health_routes) == 1, (
        f"Expected exactly one /health route, found {len(health_routes)}. "
        f"The ALB target group depends on this endpoint existing."
    )

    health_route = health_routes[0]
    assert "GET" in health_route.methods, "/health must accept GET"


def test_health_handler_returns_ok_without_db():
    """
    The /health handler must be synchronous, DB-free, and return a simple dict.
    This is called ~every 30s by the load balancer — it must never touch DB.
    """
    from financial_data_etl.api.app import health

    result = health()
    assert isinstance(result, dict)
    assert result.get("status") == "ok"


def test_root_route_is_registered():
    """GET / also exists (used by the old basic smoke path)."""
    from financial_data_etl.api.app import app

    root_routes = [
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/"
    ]
    assert len(root_routes) == 1
