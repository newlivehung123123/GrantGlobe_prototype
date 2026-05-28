"""
Unit tests for BehaviouralDelayMiddleware.

Tests:
- Delay is within [DELAY_MIN, DELAY_MAX] when no extended pause fires
- Delay respects rate_limit_floor_seconds (never below floor)
- Extended pause is added when random.random() < EXTENDED_PAUSE_PROBABILITY
- time.sleep is called with the computed delay
- Delay is never below rate_floor even when Gaussian draws below it

All time.sleep calls are mocked so tests run instantly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from scrapy.http import Request

from grantglobe_crawler.middlewares.delay import BehaviouralDelayMiddleware

_DEFAULTS = dict(
    delay_mean=4.0,
    delay_sd=1.5,
    delay_min=2.0,
    delay_max=10.0,
    extended_pause_prob=0.15,
    extended_pause_min=15.0,
    extended_pause_max=45.0,
)


def _make_middleware(**overrides) -> BehaviouralDelayMiddleware:
    return BehaviouralDelayMiddleware(**{**_DEFAULTS, **overrides})


def _make_request(url="https://example.org/", **meta) -> Request:
    m = {"domain": "example.org", "rate_limit_floor_seconds": 4.0} | meta
    return Request(url, meta=m)


def _make_spider():
    s = MagicMock()
    s.name = "grants"
    return s


class TestBehaviouralDelayMiddleware:
    def test_delay_within_min_max_range(self):
        """With a Gaussian draw inside the range, sleep is clipped to [DELAY_MIN, DELAY_MAX]."""
        mw = _make_middleware()
        req = _make_request()

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=5.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        mock_sleep.assert_called_once()
        slept = mock_sleep.call_args[0][0]
        assert _DEFAULTS["delay_min"] <= slept <= _DEFAULTS["delay_max"]

    def test_delay_clipped_to_max_when_gauss_exceeds_max(self):
        """Gaussian draw above DELAY_MAX is clipped back to DELAY_MAX."""
        mw = _make_middleware()
        req = _make_request(rate_limit_floor_seconds=4.0)

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=99.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        slept = mock_sleep.call_args[0][0]
        assert slept == _DEFAULTS["delay_max"]

    def test_delay_clipped_to_min_when_gauss_below_min(self):
        """Gaussian draw below DELAY_MIN and rate_floor is raised to DELAY_MIN."""
        mw = _make_middleware()
        # rate_floor = DELAY_MIN = 2.0 so the effective minimum is DELAY_MIN
        req = _make_request(rate_limit_floor_seconds=2.0)

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=0.1),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        slept = mock_sleep.call_args[0][0]
        assert slept == _DEFAULTS["delay_min"]

    def test_rate_limit_floor_overrides_gaussian(self):
        """rate_limit_floor_seconds takes precedence when above the Gaussian draw."""
        mw = _make_middleware()
        rate_floor = 6.0
        req = _make_request(rate_limit_floor_seconds=rate_floor)

        # Gauss returns 3.0 — below rate_floor=6.0
        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=3.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        slept = mock_sleep.call_args[0][0]
        assert slept >= rate_floor, (
            f"Delay {slept:.2f}s must not be below rate_floor {rate_floor}s"
        )

    def test_extended_pause_added_when_probability_fires(self):
        """When random.random() < EXTENDED_PAUSE_PROBABILITY, extra pause is added."""
        mw = _make_middleware(extended_pause_prob=0.50, extended_pause_min=20.0, extended_pause_max=20.0)
        req = _make_request(rate_limit_floor_seconds=4.0)

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=4.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=0.01),
            patch("grantglobe_crawler.middlewares.delay.random.uniform", return_value=20.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        slept = mock_sleep.call_args[0][0]
        # Base delay (4.0) + extended pause (20.0) = 24.0
        assert slept == pytest.approx(24.0, abs=0.01)

    def test_extended_pause_not_added_when_probability_misses(self):
        """When random.random() >= EXTENDED_PAUSE_PROBABILITY, no extra pause."""
        mw = _make_middleware(extended_pause_prob=0.15)
        req = _make_request(rate_limit_floor_seconds=4.0)

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=4.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=0.99),
            patch("grantglobe_crawler.middlewares.delay.random.uniform") as mock_uniform,
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        mock_uniform.assert_not_called()
        slept = mock_sleep.call_args[0][0]
        assert slept == pytest.approx(4.0, abs=0.01)

    def test_time_sleep_called_once(self):
        """time.sleep is called exactly once per request."""
        mw = _make_middleware()
        req = _make_request()

        with (
            patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=4.0),
            patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
            patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
        ):
            mw.process_request(req, _make_spider())

        assert mock_sleep.call_count == 1

    def test_delay_never_below_rate_floor_even_with_low_gauss(self):
        """Comprehensive floor check across multiple simulated draws."""
        mw = _make_middleware()
        rate_floor = 7.0

        for gauss_val in [-5.0, 0.0, 1.5, 3.0, 6.9]:
            req = _make_request(rate_limit_floor_seconds=rate_floor)
            with (
                patch("grantglobe_crawler.middlewares.delay.random.gauss", return_value=gauss_val),
                patch("grantglobe_crawler.middlewares.delay.random.random", return_value=1.0),
                patch("grantglobe_crawler.middlewares.delay.time.sleep") as mock_sleep,
            ):
                mw.process_request(req, _make_spider())

            slept = mock_sleep.call_args[0][0]
            assert slept >= rate_floor, (
                f"gauss={gauss_val}: slept={slept:.2f}s < rate_floor={rate_floor}"
            )
