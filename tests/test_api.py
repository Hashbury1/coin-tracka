"""
API tests — run with: pytest tests/test_api.py

These are "integration-style" in that they exercise the real FastAPI app,
routing, request validation, and response serialization end-to-end. The
one thing they don't hit is a real database: the SQLAlchemy session is
swapped out via FastAPI's dependency_overrides for a fake that returns
canned rows. This keeps the suite fast and runnable in CI without needing
a live TimescaleDB container, while still catching real bugs in the
routing/serialization layer (wrong field name, bad status code, broken
query param validation, etc).

A separate smoke test against the real docker-compose stack runs in CI
as the 'integration-test' job in .github/workflows/ci-cd.yml — that one
catches DB/network wiring issues this file intentionally doesn't cover.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))

from db import get_session  # noqa: E402
from main import app  # noqa: E402


def make_fake_row(**overrides):
    row = {
        "token_id": "coingecko:doge",
        "symbol": "DOGE",
        "name": "Dogecoin",
        "chain": "multi",
        "volatility_score": 42.0,
        "momentum_score": 55.0,
        "liquidity_score": 90.0,
        "composite_score": 60.0,
        "as_of": datetime.now(timezone.utc),
        "price_usd": 0.15,
    }
    row.update(overrides)
    return row


class FakeResult:
    """Mimics the object returned by AsyncSession.execute(...).mappings().all()"""

    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        outer = MagicMock()
        outer.all.return_value = self._rows
        return outer


def override_session_with_rows(rows):
    async def _fake_get_session():
        session = AsyncMock()
        session.execute.return_value = FakeResult(rows)
        yield session

    return _fake_get_session


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides don't leak between tests."""
    yield
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    def test_health_ok_when_db_reachable(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = None

        import main as main_module

        main_module.engine.connect = MagicMock(return_value=mock_ctx)

        client = TestClient(app)
        resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"

    def test_health_reports_db_unreachable_without_crashing(self):
        import main as main_module

        def raise_error(*args, **kwargs):
            raise ConnectionRefusedError("db down")

        main_module.engine.connect = raise_error

        client = TestClient(app)
        resp = client.get("/health")

        # The endpoint itself should still respond 200 - it reports DB
        # status in the body rather than failing the whole health check.
        assert resp.status_code == 200
        assert resp.json()["database"] == "unreachable"


class TestRankedCoinsEndpoint:
    def test_returns_ranked_results(self):
        rows = [
            make_fake_row(token_id="a", symbol="AAA", composite_score=90.0),
            make_fake_row(token_id="b", symbol="BBB", composite_score=50.0),
        ]
        app.dependency_overrides[get_session] = override_session_with_rows(rows)

        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert "not financial advice" in body["disclaimer"].lower()

    def test_results_sorted_by_composite_score_descending(self):
        rows = [
            make_fake_row(token_id="low", symbol="LOW", composite_score=10.0),
            make_fake_row(token_id="high", symbol="HIGH", composite_score=95.0),
        ]
        app.dependency_overrides[get_session] = override_session_with_rows(rows)

        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked")

        symbols = [r["symbol"] for r in resp.json()["results"]]
        assert symbols == ["HIGH", "LOW"]

    def test_empty_results_returns_empty_list_not_error(self):
        app.dependency_overrides[get_session] = override_session_with_rows([])

        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked")

        assert resp.status_code == 200
        assert resp.json() == {
            "count": 0,
            "disclaimer": resp.json()["disclaimer"],
            "results": [],
        }

    def test_limit_param_caps_results(self):
        rows = [make_fake_row(token_id=str(i), symbol=f"T{i}", composite_score=float(i)) for i in range(10)]
        app.dependency_overrides[get_session] = override_session_with_rows(rows)

        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked?limit=3")

        assert resp.json()["count"] == 3

    def test_limit_over_max_is_rejected(self):
        app.dependency_overrides[get_session] = override_session_with_rows([])
        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked?limit=500")
        assert resp.status_code == 422

    def test_negative_min_score_is_rejected(self):
        app.dependency_overrides[get_session] = override_session_with_rows([])
        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked?min_score=-5")
        assert resp.status_code == 422

    def test_response_matches_expected_schema(self):
        rows = [make_fake_row()]
        app.dependency_overrides[get_session] = override_session_with_rows(rows)

        client = TestClient(app)
        resp = client.get("/api/v1/coins/ranked")
        result = resp.json()["results"][0]

        expected_keys = {
            "token_id", "symbol", "name", "chain", "price_usd",
            "volatility_score", "momentum_score", "liquidity_score",
            "composite_score", "as_of",
        }
        assert set(result.keys()) == expected_keys


class TestTokenHistoryEndpoint:
    def test_returns_price_points(self):
        async def _fake_get_session():
            session = AsyncMock()
            fake_rows = [
                {"time": datetime.now(timezone.utc), "price_usd": 0.1, "volume_24h_usd": 1000},
                {"time": datetime.now(timezone.utc), "price_usd": 0.11, "volume_24h_usd": 1200},
            ]
            session.execute.return_value = FakeResult(fake_rows)
            yield session

        app.dependency_overrides[get_session] = _fake_get_session

        client = TestClient(app)
        resp = client.get("/api/v1/coins/coingecko:dogecoin/history")

        assert resp.status_code == 200
        body = resp.json()
        assert body["token_id"] == "coingecko:dogecoin"
        assert len(body["points"]) == 2
        assert body["points"][0]["price_usd"] == 0.1


class TestErrorHandling:
    def test_unknown_route_returns_404(self):
        client = TestClient(app)
        resp = client.get("/api/v1/coins/not-a-real-route/nonsense")
        assert resp.status_code == 404

    def test_unhandled_exception_does_not_leak_internals(self):
        async def _broken_session():
            session = AsyncMock()
            session.execute.side_effect = RuntimeError("something exploded internally")
            yield session

        app.dependency_overrides[get_session] = _broken_session

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/coins/ranked")

        assert resp.status_code == 500
        assert "something exploded internally" not in resp.text
        assert resp.json() == {"detail": "Internal server error"}


class TestCORSAndMethodRestrictions:
    def test_only_get_is_allowed(self):
        client = TestClient(app)
        resp = client.post("/api/v1/coins/ranked")
        assert resp.status_code == 405