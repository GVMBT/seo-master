"""Tests for services/external/pagespeed.py -- PageSpeed Insights client.

Covers: audit (success, timeout, HTTP error, retry, partial data),
score extraction, metric extraction, recommendations extraction.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from services.external.pagespeed import (
    PageSpeedClient,
    _extract_cls_metric,
    _extract_metric,
    _extract_recommendations,
    _extract_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler: object, api_key: str = "") -> PageSpeedClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=transport)
    return PageSpeedClient(http_client=http, api_key=api_key)


def _psi_response(
    perf_score: float = 0.85,
    lcp_ms: int = 2500,
    inp_ms: int = 200,
    cls_percentile: int = 10,
    ttfb_ms: int = 800,
    tbt_value: float = 300.0,
    speed_index_value: float = 3000.0,
    fcp_value: float = 1500.0,
) -> dict[str, Any]:
    """Build a realistic PSI API response."""
    return {
        "id": "https://example.com/",
        "lighthouseResult": {
            "categories": {
                "performance": {"score": perf_score},
                "accessibility": {"score": 0.92},
                "best-practices": {"score": 0.88},
                "seo": {"score": 0.95},
            },
            "audits": {
                "total-blocking-time": {"numericValue": tbt_value},
                "speed-index": {"numericValue": speed_index_value},
                "first-contentful-paint": {"numericValue": fcp_value},
                "render-blocking-resources": {
                    "title": "Eliminate render-blocking resources",
                    "description": "Resources are blocking...",
                    "score": 0.3,
                },
                "unused-css-rules": {
                    "title": "Reduce unused CSS",
                    "description": "Reduce unused rules...",
                    "score": 1.0,  # Good -- should not appear in recommendations
                },
                "uses-optimized-images": {
                    "title": "Optimize images",
                    "description": "Use optimized images...",
                    "score": 0,
                },
            },
        },
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": lcp_ms},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": inp_ms},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": cls_percentile},
                "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"percentile": ttfb_ms},
            },
        },
    }


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_extract_score(self) -> None:
        categories = {"performance": {"score": 0.85}}
        assert _extract_score(categories, "performance") == 85

    def test_extract_score_none(self) -> None:
        categories = {"performance": {"score": None}}
        assert _extract_score(categories, "performance") == 0

    def test_extract_score_missing_key(self) -> None:
        assert _extract_score({}, "performance") == 0

    def test_extract_metric(self) -> None:
        metrics = {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2500}}
        assert _extract_metric(metrics, "LARGEST_CONTENTFUL_PAINT_MS") == 2500

    def test_extract_metric_missing(self) -> None:
        assert _extract_metric({}, "NONEXISTENT") == 0

    def test_extract_cls_metric(self) -> None:
        metrics = {"CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 10}}
        assert _extract_cls_metric(metrics) == pytest.approx(0.1)

    def test_extract_cls_metric_zero(self) -> None:
        metrics = {"CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 0}}
        assert _extract_cls_metric(metrics) == 0.0

    def test_extract_recommendations(self) -> None:
        lighthouse = {
            "audits": {
                "render-blocking-resources": {
                    "title": "Eliminate render-blocking",
                    "description": "Resources...",
                    "score": 0.3,
                },
                "unused-css-rules": {
                    "title": "Reduce unused CSS",
                    "description": "...",
                    "score": 1.0,  # Perfect score -- not a recommendation
                },
                "uses-optimized-images": {
                    "title": "Optimize images",
                    "description": "...",
                    "score": 0,  # Worst score -- high priority
                },
            },
        }
        recs = _extract_recommendations(lighthouse)
        assert len(recs) == 2
        titles = [r["title"] for r in recs]
        assert "Eliminate render-blocking" in titles
        assert "Optimize images" in titles

        # Check priority assignment
        img_rec = next(r for r in recs if r["title"] == "Optimize images")
        assert img_rec["priority"] == "high"

        block_rec = next(r for r in recs if r["title"] == "Eliminate render-blocking")
        assert block_rec["priority"] == "medium"


# ---------------------------------------------------------------------------
# audit -- success
# ---------------------------------------------------------------------------


class TestAuditSuccess:
    async def test_basic_audit(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "pagespeedonline" in str(request.url):
                return httpx.Response(200, json=_psi_response())
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.audit("https://example.com")

        assert result is not None
        assert result.performance_score == 85
        assert result.accessibility_score == 92
        assert result.best_practices_score == 88
        assert result.seo_score == 95
        assert result.lcp_ms == 2500
        assert result.inp_ms == 200
        assert result.cls == pytest.approx(0.1)
        assert result.ttfb_ms == 800
        assert result.tbt_ms == 300
        assert result.speed_index == 3000
        assert result.fcp_ms == 1500
        assert len(result.recommendations) >= 1
        assert "full_report" not in result.recommendations  # sanity check
        assert isinstance(result.full_report, dict)

    async def test_sends_correct_params(self) -> None:
        captured_url: str | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_psi_response())

        client = _make_client(handler)
        await client.audit("https://example.com", strategy="desktop")

        assert captured_url is not None
        assert "strategy=desktop" in captured_url
        assert "url=https" in captured_url

    async def test_sends_all_four_categories(self) -> None:
        captured_url: str | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_psi_response())

        client = _make_client(handler)
        await client.audit("https://example.com")

        assert captured_url is not None
        for cat in ("PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"):
            assert f"category={cat}" in captured_url

    async def test_api_key_included_when_provided(self) -> None:
        captured_url: str | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_psi_response())

        client = _make_client(handler, api_key="my-api-key")
        await client.audit("https://example.com")

        assert captured_url is not None
        assert "key=my-api-key" in captured_url

    async def test_no_api_key_in_params_when_empty(self) -> None:
        captured_url: str | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_psi_response())

        client = _make_client(handler, api_key="")
        await client.audit("https://example.com")

        assert captured_url is not None
        assert "key=" not in captured_url


# ---------------------------------------------------------------------------
# audit -- error handling
# ---------------------------------------------------------------------------


class TestAuditErrors:
    async def test_timeout_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out")

        client = _make_client(handler)
        result = await client.audit("https://slow-site.com")
        assert result is None

    async def test_http_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = _make_client(handler)
        result = await client.audit("https://example.com")
        assert result is None

    async def test_network_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        result = await client.audit("https://unreachable.com")
        assert result is None

    async def test_retry_succeeds_on_second_attempt(self) -> None:
        attempt = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                return httpx.Response(500, text="Error")
            return httpx.Response(200, json=_psi_response(perf_score=0.75))

        client = _make_client(handler)
        result = await client.audit("https://example.com")

        assert result is not None
        assert result.performance_score == 75

    async def test_all_retries_exhausted_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Always fails")

        client = _make_client(handler)
        result = await client.audit("https://example.com")
        assert result is None


# ---------------------------------------------------------------------------
# audit -- partial/missing data
# ---------------------------------------------------------------------------


class TestAuditPartialData:
    async def test_missing_loading_experience(self) -> None:
        """Some sites have no field data (loadingExperience)."""

        async def handler(request: httpx.Request) -> httpx.Response:
            response = _psi_response()
            response["loadingExperience"] = {}
            return httpx.Response(200, json=response)

        client = _make_client(handler)
        result = await client.audit("https://new-site.com")

        assert result is not None
        assert result.performance_score == 85  # Lighthouse still works
        assert result.lcp_ms == 0  # No field data
        assert result.inp_ms == 0

    async def test_missing_categories(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            response = _psi_response()
            response["lighthouseResult"]["categories"] = {}
            return httpx.Response(200, json=response)

        client = _make_client(handler)
        result = await client.audit("https://example.com")

        assert result is not None
        assert result.performance_score == 0
        assert result.seo_score == 0
