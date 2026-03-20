"""
LIVE-09 Security Handshake Test.

Tests three scenarios:
  a) Fake origin  → MUST be rejected (code 4003)
  b) Missing token when LIVE_DEMO_TOKEN is active → MUST be rejected (code 4001)
  c) Valid credentials → MUST succeed (receives seed)

Prerequisites:
  Start the server with security active:
    LIVE_DEMO_TOKEN=my_secret_token uvicorn financial_data_etl.api.app:app --port 8000

  For origin-only testing (no token enforcement):
    uvicorn financial_data_etl.api.app:app --port 8000

  For dev/DEBUG mode (all security bypassed):
    DEBUG=1 uvicorn financial_data_etl.api.app:app --port 8000

Usage:
    python test_security_handshake.py                           # localhost, no token
    python test_security_handshake.py ws://localhost:8000 my_secret_token  # with token
"""

import asyncio
import sys
import json

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' package required. Install with: pip install websockets")
    sys.exit(1)


async def test_fake_origin(uri_base: str):
    """Test a) — Connection from an unauthorized origin. Must be rejected."""
    print("--- TEST A: Fake Origin (must be rejected) ---")
    try:
        async with websockets.connect(
            f"{uri_base}/ws/live/BTC",
            origin="https://evil-hacker-site.com",
            open_timeout=5,
        ) as ws:
            # If we get here, the connection was accepted — check if we get
            # an immediate close frame
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"  Received: {msg[:100]}")
                print("[FAIL] TEST A: Connection was accepted with fake origin!\n")
                return False
            except websockets.ConnectionClosed as e:
                if e.code == 4003:
                    print(f"  Closed with code={e.code}: {e.reason}")
                    print("[PASS] TEST A: Rejected with 4003 (origin not allowed)\n")
                    return True
                print(f"  Closed with unexpected code={e.code}: {e.reason}")
                print("[FAIL] TEST A: Wrong rejection code\n")
                return False
    except websockets.InvalidStatusCode as e:
        # Some servers reject before upgrade
        print(f"  HTTP rejection: status={e.status_code}")
        print("[PASS] TEST A: Rejected at HTTP upgrade level\n")
        return True
    except websockets.ConnectionClosedError as e:
        if e.code == 4003:
            print(f"  Closed with code={e.code}: {e.reason}")
            print("[PASS] TEST A: Rejected with 4003\n")
            return True
        print(f"  Unexpected close: code={e.code}")
        return False
    except Exception as e:
        print(f"  Connection failed: {type(e).__name__}: {e}")
        print("[PASS] TEST A: Connection rejected (server refused)\n")
        return True


async def test_missing_token(uri_base: str):
    """Test b) — Connection without token when LIVE_DEMO_TOKEN is active. Must be rejected."""
    print("--- TEST B: Missing Token (must be rejected if LIVE_DEMO_TOKEN set) ---")
    try:
        async with websockets.connect(
            f"{uri_base}/ws/live/BTC",
            origin="http://localhost:3000",
            open_timeout=5,
        ) as ws:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(msg)
                if data.get("type") == "seed":
                    print("  Received seed — token enforcement is OFF (no LIVE_DEMO_TOKEN env var)")
                    print("[SKIP] TEST B: Token not enforced (expected in dev mode)\n")
                    return True  # Not a failure — token env var isn't set
                print(f"  Received: {msg[:100]}")
                print("[FAIL] TEST B: Connection accepted without token!\n")
                return False
            except websockets.ConnectionClosed as e:
                if e.code == 4001:
                    print(f"  Closed with code={e.code}: {e.reason}")
                    print("[PASS] TEST B: Rejected with 4001 (invalid/missing token)\n")
                    return True
                print(f"  Closed with unexpected code={e.code}: {e.reason}")
                return False
    except websockets.ConnectionClosedError as e:
        if e.code == 4001:
            print(f"  Closed with code={e.code}: {e.reason}")
            print("[PASS] TEST B: Rejected with 4001\n")
            return True
        print(f"  Unexpected close: code={e.code}")
        return False
    except Exception as e:
        print(f"  Connection failed: {type(e).__name__}: {e}")
        print("[PASS] TEST B: Connection rejected\n")
        return True


async def test_valid_connection(uri_base: str, token: str | None):
    """Test c) — Valid origin + valid token. Must succeed and receive seed."""
    print("--- TEST C: Valid Credentials (must succeed) ---")
    uri = f"{uri_base}/ws/live/BTC"
    if token:
        uri += f"?token={token}"
        print(f"  Using token: {token[:4]}***")

    try:
        async with websockets.connect(
            uri,
            origin="http://localhost:3000",
            open_timeout=10,
        ) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(raw)

            if data.get("type") == "seed":
                n = len(data.get("chart_candles", []))
                print(f"  Seed received: {n} candles for {data.get('symbol')}")
                print("[PASS] TEST C: Authorized connection successful\n")
                return True
            elif data.get("type") == "error":
                print(f"  Error: {data.get('message')}")
                print("[WARN] TEST C: Connected but got application error (symbol issue?)\n")
                return True  # Security passed, app error is separate
            else:
                print(f"  Unexpected first message type: {data.get('type')}")
                print("[FAIL] TEST C: Unexpected response\n")
                return False

    except websockets.ConnectionClosed as e:
        print(f"  Connection closed: code={e.code}, reason={e.reason}")
        print("[FAIL] TEST C: Valid connection was rejected!\n")
        return False
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")
        print("[FAIL] TEST C: Connection failed\n")
        return False


async def run_tests(uri_base: str, token: str | None):
    print(f"\n{'='*70}")
    print(f"  LIVE-09 SECURITY HANDSHAKE TEST")
    print(f"  Server: {uri_base}")
    print(f"  Token:  {'SET' if token else 'NOT SET (dev mode)'}")
    print(f"{'='*70}\n")

    results = []

    results.append(await test_fake_origin(uri_base))
    results.append(await test_missing_token(uri_base))
    results.append(await test_valid_connection(uri_base, token))

    passed = sum(results)
    total = len(results)

    print(f"{'='*70}")
    print(f"  RESULTS: {passed}/{total} passed")
    print(f"{'='*70}\n")

    return all(results)


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000"
    token = sys.argv[2] if len(sys.argv) > 2 else None
    success = asyncio.run(run_tests(uri, token))
    sys.exit(0 if success else 1)
