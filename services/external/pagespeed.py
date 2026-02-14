"""PageSpeed Insights client for site audits (F28/F30).

Spec: docs/API_CONTRACTS.md section 8.4
Mapping: PSI JSON -> site_audits table columns.

Free tier: 25,000 requests/day (no API key needed, but rate limited).
Retry: 2 attempts. On timeout (>30s) -> save partial data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

PSI_API_BASE = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_PSI_TIMEOUT = 60.0  # PSI can be slow


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Result of a PageSpeed Insights audit.

    Matches site_audits table columns (ARCHITECTURE.md section 3).
    """

    performance_score: int  # 0-100
    accessibility_score: int  # 0-100
    best_practices_score: int  # 0-100
    seo_score: int  # 0-100
    fcp_ms: int  # First Contentful Paint
    lcp_ms: int  # Largest Contentful Paint
    cls: float  # Cumulative Layout Shift
    tbt_ms: int  # Total Blocking Time
    inp_ms: int  # Interaction to Next Paint
    ttfb_ms: int  # Time to First Byte
    speed_index: int
    recommendations: list[dict[str, str]]  # [{title, description, priority}]
    full_report: dict[str, Any]  # Full PSI API JSON


def _extract_score(categories: dict[str, Any], key: str) -> int:
    """Extract a category score (0-100) from Lighthouse result."""
    cat = categories.get(key, {})
    raw = cat.get("score")
    if raw is None:
        return 0
    return int(raw * 100)


def _extract_metric(metrics: dict[str, Any], key: str) -> int:
    """Extract a metric percentile from loadingExperience."""
    metric = metrics.get(key, {})
    return int(metric.get("percentile", 0))


def _extract_cls_metric(metrics: dict[str, Any]) -> float:
    """Extract CLS as a float (percentile / 100)."""
    metric = metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {})
    percentile = int(metric.get("percentile", 0))
    return percentile / 100.0


def _extract_audits_from_lighthouse(lighthouse: dict[str, Any]) -> int:
    """Extract TBT from Lighthouse audits (not in loadingExperience)."""
    audits = lighthouse.get("audits", {})
    tbt = audits.get("total-blocking-time", {})
    return int(tbt.get("numericValue", 0))


def _extract_speed_index(lighthouse: dict[str, Any]) -> int:
    """Extract Speed Index from Lighthouse audits."""
    audits = lighthouse.get("audits", {})
    si = audits.get("speed-index", {})
    return int(si.get("numericValue", 0))


def _extract_fcp(lighthouse: dict[str, Any]) -> int:
    """Extract FCP from Lighthouse audits."""
    audits = lighthouse.get("audits", {})
    fcp = audits.get("first-contentful-paint", {})
    return int(fcp.get("numericValue", 0))


def _extract_recommendations(lighthouse: dict[str, Any]) -> list[dict[str, str]]:
    """Extract actionable recommendations from Lighthouse audits.

    Returns [{title, description, priority}] for audits that have suggestions.
    """
    audits = lighthouse.get("audits", {})
    recommendations: list[dict[str, str]] = []

    # Priority audits to check
    priority_audits = [
        "render-blocking-resources",
        "unused-css-rules",
        "unused-javascript",
        "modern-image-formats",
        "uses-optimized-images",
        "uses-text-compression",
        "uses-responsive-images",
        "offscreen-images",
        "efficient-animated-content",
        "unminified-css",
        "unminified-javascript",
        "server-response-time",
        "redirects",
        "uses-rel-preconnect",
        "uses-rel-preload",
        "font-display",
        "third-party-summary",
        "largest-contentful-paint-element",
        "dom-size",
        "critical-request-chains",
    ]

    for audit_id in priority_audits:
        audit = audits.get(audit_id, {})
        score = audit.get("score")
        if score is not None and score < 1.0:
            title = audit.get("title", audit_id)
            description = audit.get("description", "")
            # Determine priority from score
            if score == 0:
                priority = "high"
            elif score < 0.5:
                priority = "medium"
            else:
                priority = "low"
            recommendations.append({
                "title": title,
                "description": description,
                "priority": priority,
            })

    return recommendations


class PageSpeedClient:
    """Client for Google PageSpeed Insights API v5.

    Uses shared httpx.AsyncClient (never creates its own).
    Free tier: 25,000 requests/day.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str = "",
    ) -> None:
        self._http = http_client
        self._api_key = api_key

    async def audit(
        self,
        url: str,
        strategy: str = "mobile",
    ) -> AuditResult | None:
        """Run PageSpeed Insights audit.

        GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed
        Params: url, strategy, category (performance, accessibility, best-practices, seo), key.

        Returns AuditResult on success, None on failure.
        Retry: 2 attempts. On timeout (>30s) -> None.
        """
        result = await self._audit_with_retry(url, strategy, attempts=2)
        return result

    async def _audit_with_retry(
        self,
        url: str,
        strategy: str,
        attempts: int,
    ) -> AuditResult | None:
        """Execute audit with retry logic."""
        last_error: str = ""

        for attempt in range(1, attempts + 1):
            try:
                params: dict[str, str] = {
                    "url": url,
                    "strategy": strategy,
                    "category": "PERFORMANCE",
                }
                if self._api_key:
                    params["key"] = self._api_key

                resp = await self._http.get(
                    PSI_API_BASE,
                    params=params,
                    timeout=_PSI_TIMEOUT,
                )
                resp.raise_for_status()
                body = resp.json()

                return self._parse_response(body)

            except httpx.TimeoutException:
                last_error = "timeout"
                log.warning(
                    "pagespeed.audit_timeout",
                    url=url,
                    attempt=attempt,
                )
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = str(exc)
                log.warning(
                    "pagespeed.audit_attempt_failed",
                    url=url,
                    attempt=attempt,
                    error=last_error,
                )

        log.warning(
            "pagespeed.audit_failed_all_attempts",
            url=url,
            attempts=attempts,
            last_error=last_error,
        )
        return None

    def _parse_response(self, body: dict[str, Any]) -> AuditResult:
        """Parse PSI API response into AuditResult.

        Mapping from docs/API_CONTRACTS.md section 8.4.
        """
        lighthouse = body.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        loading_exp = body.get("loadingExperience", {})
        metrics = loading_exp.get("metrics", {})

        performance_score = _extract_score(categories, "performance")
        accessibility_score = _extract_score(categories, "accessibility")
        best_practices_score = _extract_score(categories, "best-practices")
        seo_score = _extract_score(categories, "seo")

        # loadingExperience metrics (field data)
        lcp_ms = _extract_metric(metrics, "LARGEST_CONTENTFUL_PAINT_MS")
        inp_ms = _extract_metric(metrics, "INTERACTION_TO_NEXT_PAINT")
        cls = _extract_cls_metric(metrics)
        ttfb_ms = _extract_metric(metrics, "EXPERIMENTAL_TIME_TO_FIRST_BYTE")

        # Lighthouse audits (lab data)
        tbt_ms = _extract_audits_from_lighthouse(lighthouse)
        speed_index = _extract_speed_index(lighthouse)
        fcp_ms = _extract_fcp(lighthouse)
        recommendations = _extract_recommendations(lighthouse)

        result = AuditResult(
            performance_score=performance_score,
            accessibility_score=accessibility_score,
            best_practices_score=best_practices_score,
            seo_score=seo_score,
            fcp_ms=fcp_ms,
            lcp_ms=lcp_ms,
            cls=cls,
            tbt_ms=tbt_ms,
            inp_ms=inp_ms,
            ttfb_ms=ttfb_ms,
            speed_index=speed_index,
            recommendations=recommendations,
            full_report=body,
        )

        log.info(
            "pagespeed.audit_success",
            url=body.get("id", ""),
            performance=performance_score,
            lcp_ms=lcp_ms,
            cls=cls,
        )
        return result
