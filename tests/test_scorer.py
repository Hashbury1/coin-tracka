"""
Run with: pytest tests/test_scorer.py
Requires services/scoring on the path — see pytest.ini / conftest sys.path hack below.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "scoring"))

from scorer import (  # noqa: E402
    composite_score,
    liquidity_score,
    log_returns,
    momentum_score,
    score_token,
    volatility_score,
)


class TestLogReturns:
    def test_empty_input(self):
        assert list(log_returns([])) == []

    def test_single_price_returns_empty(self):
        assert list(log_returns([1.0])) == []

    def test_filters_non_positive_prices(self):
        result = log_returns([1.0, -1.0, 2.0, 0.0, 4.0])
        assert len(result) == 2  # only 1.0 -> 2.0 -> 4.0 survive the filter


class TestVolatilityScore:
    def test_flat_price_series_is_zero_volatility(self):
        assert volatility_score([1.0, 1.0, 1.0, 1.0]) == 0.0

    def test_wildly_swinging_price_scores_high(self):
        prices = [1.0, 2.0, 0.5, 3.0, 0.2, 4.0]
        score = volatility_score(prices)
        assert score > 50

    def test_insufficient_data_returns_zero(self):
        assert volatility_score([1.0]) == 0.0


class TestMomentumScore:
    def test_no_movement_no_volume_is_low(self):
        score = momentum_score([1.0, 1.0], [100, 100])
        assert score < 5

    def test_price_up_and_volume_spike_scores_high(self):
        prices = [1.0, 1.5]
        volumes = [100, 100, 100, 1000]  # big spike on last read
        score = momentum_score(prices, volumes)
        assert score > 30

    def test_single_price_point_returns_zero(self):
        assert momentum_score([1.0], [100]) == 0.0


class TestLiquidityScore:
    def test_zero_liquidity_is_zero(self):
        assert liquidity_score(0) == 0.0

    def test_below_floor_scales_linearly(self):
        score = liquidity_score(10_000, min_liquidity_usd=20_000)
        assert 0 < score < 20

    def test_above_floor_scores_higher_than_below(self):
        below = liquidity_score(10_000, min_liquidity_usd=20_000)
        above = liquidity_score(100_000, min_liquidity_usd=20_000)
        assert above > below

    def test_capped_at_100(self):
        assert liquidity_score(10_000_000_000, min_liquidity_usd=20_000) <= 100


class TestCompositeScore:
    def test_weighted_average_within_bounds(self):
        score = composite_score(80, 60, 40)
        assert 0 <= score <= 100

    def test_all_zero_inputs_gives_zero(self):
        assert composite_score(0, 0, 0) == 0.0


class TestScoreToken:
    def test_returns_all_four_keys(self):
        result = score_token(
            prices=[1.0, 1.2, 0.9, 1.5],
            volumes=[100, 200, 150, 500],
            liquidity_usd=50_000,
        )
        assert set(result.keys()) == {
            "volatility_score",
            "momentum_score",
            "liquidity_score",
            "composite_score",
        }

    def test_low_liquidity_pulls_composite_down(self):
        base_args = dict(prices=[1.0, 1.2, 0.9, 1.5], volumes=[100, 200, 150, 500])
        high_liq = score_token(**base_args, liquidity_usd=1_000_000)
        low_liq = score_token(**base_args, liquidity_usd=100)
        assert low_liq["composite_score"] < high_liq["composite_score"]
