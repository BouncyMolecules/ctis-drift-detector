"""Synchronous CTIS public API transport (httpx) — Streamlit-free."""
from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ctis_drift.utils.logging import get_logger, log_unexpected_error

logger = get_logger(__name__)

CTIS_PUBLIC_API_BASE_URL: Final[HttpUrl] = HttpUrl("https://euclinicaltrials.eu/ctis-public-api")
DEFAULT_TIMEOUT_SECONDS: Final[float] = 60.0
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 900
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS: Final[float] = 0.25
DEFAULT_BACKOFF_SECONDS: Final[float] = 0.5
DEFAULT_BACKOFF_FACTOR: Final[float] = 2.0
DEFAULT_BACKOFF_CAP_SECONDS: Final[float] = 8.0
DEFAULT_MAX_TOTAL_RETRIES: Final[int] = 4

_HTTP_RETRY_STATUSES: Final[frozenset[int]] = frozenset({500, 502, 503, 504})

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CtisPublicApiError(RuntimeError):
    """Base error for failures while calling the CTIS public API."""

    url: str

    def __init__(self, message: str, *, url: str) -> None:
        super().__init__(message)
        self.url = url


class CtisTransportError(CtisPublicApiError):
    """Network / TLS / connectivity failure before a complete HTTP response."""


class CtisTimeoutError(CtisPublicApiError):
    """Timed out communicating with CTIS."""

    def __init__(self, message: str, *, url: str, timeout_seconds: float) -> None:
        super().__init__(message, url=url)
        self.timeout_seconds = timeout_seconds


class CtisHttpResponseError(CtisPublicApiError):
    """CTIS responded with HTTP status indicating failure."""

    status_code: int

    def __init__(
        self,
        message: str,
        *,
        url: str,
        status_code: int,
        body_preview: str | None,
    ) -> None:
        super().__init__(message, url=url)
        self.status_code = status_code
        self.body_preview = body_preview


class CtisRateLimitError(CtisHttpResponseError):
    """Server asked the client to back off (HTTP 429 or explicit rate limiting)."""


class CtisMalformedJsonError(CtisPublicApiError):
    """Response body was supposed to be JSON but could not be decoded or validated."""

    def __init__(self, message: str, *, url: str, preview: str | None) -> None:
        super().__init__(message, url=url)
        self.preview = preview


# Backwards-compat alias used by legacy UI codepaths.
CTISAPIError = CtisPublicApiError


# ---------------------------------------------------------------------------
# Request / response models (search + retrieve)
# ---------------------------------------------------------------------------


class SearchPagination(BaseModel):
    """Pagination block used in POST ``/search`` request bodies."""

    model_config = ConfigDict(extra="ignore")

    page: int = Field(default=1, ge=1, description="1-based index as used by CTIS.")
    size: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Page size capped at a pragmatic upper bound.",
    )


class SearchSort(BaseModel):
    """Sort block for POST ``/search``. CTIS recognises several sort properties."""

    model_config = ConfigDict(extra="ignore")

    property: str = Field(default="decisionDate", description="Backend sort field name.")
    direction: str = Field(default="DESC", pattern=r"(?i)ASC|DESC")


class TrialSearchCriteria(BaseModel):
    """Open-ended CTIS filters; omit or set keys to ``null`` server-side semantics."""

    model_config = ConfigDict(extra="ignore")

    contain_all: list[str] | None = Field(default=None, alias="containAll")
    contain_any: list[str] | None = Field(default=None, alias="containAny")
    contain_not: list[str] | None = Field(default=None, alias="containNot")
    title: str | None = None
    number: str | None = None
    status: str | None = None
    medical_condition: str | None = Field(default=None, alias="medicalCondition")
    sponsor: str | None = None
    end_point: str | None = Field(default=None, alias="endPoint")
    product_name: str | None = Field(default=None, alias="productName")
    product_role: str | None = Field(default=None, alias="productRole")
    population_type: str | None = Field(default=None, alias="populationType")
    orphan_designation: bool | None = Field(default=None, alias="orphanDesignation")
    msc: str | None = None
    age_group_code: str | None = Field(default=None, alias="ageGroupCode")
    therapeutic_area_code: str | None = Field(default=None, alias="therapeuticAreaCode")
    trial_phase_code: str | None = Field(default=None, alias="trialPhaseCode")
    sponsor_type_code: str | None = Field(default=None, alias="sponsorTypeCode")
    gender: str | None = None
    protocol_code: str | None = Field(default=None, alias="protocolCode")
    rare_disease: bool | None = Field(default=None, alias="rareDisease")
    pip: bool | None = None
    have_orphan_designation: bool | None = Field(default=None, alias="haveOrphanDesignation")
    has_study_results: bool | None = Field(default=None, alias="hasStudyResults")
    has_clinical_study_report: bool | None = Field(default=None, alias="hasClinicalStudyReport")
    is_low_intervention: bool | None = Field(default=None, alias="isLowIntervention")
    has_serious_breach: bool | None = Field(default=None, alias="hasSeriousBreach")
    has_unexpected_event: bool | None = Field(default=None, alias="hasUnexpectedEvent")
    has_urgent_safety_measure: bool | None = Field(default=None, alias="hasUrgentSafetyMeasure")
    is_transitioned: bool | None = Field(default=None, alias="isTransitioned")
    eudra_ct_code: str | None = Field(default=None, alias="eudraCtCode")
    trial_region: str | None = Field(default=None, alias="trialRegion")
    vulnerable_population: bool | None = Field(default=None, alias="vulnerablePopulation")
    msc_status: str | None = Field(default=None, alias="mscStatus")


class TrialSearchPayload(BaseModel):
    """Fully specified JSON body accepted by POST ``/search``.

    Pass an empty criteria object (default) for an unfiltered list with pagination/sort only.
    """

    model_config = ConfigDict(extra="ignore")

    pagination: SearchPagination = Field(default_factory=SearchPagination)
    sort: SearchSort | None = Field(default_factory=lambda: SearchSort())
    search_criteria: TrialSearchCriteria = Field(
        default_factory=TrialSearchCriteria,
        alias="searchCriteria",
    )


class SearchResponsePagination(BaseModel):
    """Pagination envelope returned alongside search hits."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total_records: int = Field(alias="totalRecords")
    current_page: int = Field(alias="currentPage")
    total_pages: int = Field(alias="totalPages")
    next_page: bool = Field(alias="nextPage")
    prev_page: bool = Field(alias="prevPage")


class TrialSearchSummary(BaseModel):
    """One row from the ``search`` endpoint ``data`` array."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ct_number: str = Field(alias="ctNumber")
    ct_status: int = Field(alias="ctStatus")
    ct_title: str = Field(alias="ctTitle")
    short_title: str | None = Field(default=None, alias="shortTitle")
    conditions: str | None = None
    trial_countries: list[str] | None = Field(default=None, alias="trialCountries")
    decision_date_overall: str | None = Field(default=None, alias="decisionDateOverall")
    decision_date: str | None = Field(default=None, alias="decisionDate")
    therapeutic_areas: list[str] | None = Field(default=None, alias="therapeuticAreas")
    sponsor: str | None = None
    sponsor_type: str | None = Field(default=None, alias="sponsorType")
    trial_phase: str | None = Field(default=None, alias="trialPhase")
    end_point: str | None = Field(default=None, alias="endPoint")
    product: str | None = None
    age_range_secondary: list[str] | None = Field(default=None, alias="ageRangeSecondary")
    age_group: str | None = Field(default=None, alias="ageGroup")
    gender: str | None = None
    trial_region: int | None = Field(default=None, alias="trialRegion")
    total_number_enrolled: str | None = Field(default=None, alias="totalNumberEnrolled")
    primary_end_point: str | None = Field(default=None, alias="primaryEndPoint")
    results_first_received: str | None = Field(default=None, alias="resultsFirstReceived")
    last_updated: str | None = Field(default=None, alias="lastUpdated")
    last_publication_update: str | None = Field(default=None, alias="lastPublicationUpdate")


class TrialSearchResponse(BaseModel):
    """Typed wrapper for POST ``/search`` JSON."""

    model_config = ConfigDict(extra="ignore")

    show_warning: bool = Field(alias="showWarning")
    pagination: SearchResponsePagination
    data: list[TrialSearchSummary]


class TrialFullRecord(BaseModel):
    """Full retrieve payload returned by GET ``/retrieve/{euct}``.

    The JSON is deeply nested; only stable top-level fields are modelled strictly.
    All additional keys remain accessible via ``model_extra`` after validation
    (:attr:`model_extra` populated because ``extra="allow"``).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ct_number: str = Field(alias="ctNumber")
    ct_status: str = Field(alias="ctStatus")
    start_date_eu: str | None = Field(default=None, alias="startDateEU")
    decision_date: str | None = Field(default=None, alias="decisionDate")
    publish_date: str | None = Field(default=None, alias="publishDate")
    ct_public_status_code: int | None = Field(default=None, alias="ctPublicStatusCode")
    authorized_application: dict[str, Any] | None = Field(
        default=None,
        alias="authorizedApplication",
    )


def _sleep_respectfully(seconds: float) -> None:
    if seconds <= 0:
        return
    logger.debug("Throttling CTIS requests for %.3fs", seconds)
    time.sleep(seconds)


def _parse_retry_after_seconds(value: str) -> float | None:
    try:
        parsed = float(value.strip())
        if parsed >= 0:
            return parsed
        return None
    except ValueError:
        return None


def _json_preview(text: str, *, limit: int = 480) -> str:
    condensed = text.replace("\r", "").replace("\n", " ").strip()
    if len(condensed) <= limit:
        return condensed
    return f"{condensed[:limit]}…"


class CtisPublicClient:
    """Session-oriented synchronous client built on ``httpx.Client``.

    Retries bounded transient failures (timeouts, connectivity, selective HTTP statuses)
    using exponential backoff with deterministic jitter.

    Instances are reusable and thread-safe for typical Streamlit / single-process use.
    """

    def __init__(
        self,
        *,
        base_url: str | HttpUrl = CTIS_PUBLIC_API_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = "ctis-drift-detector/0.1 (+https://github.com/example/ctis-drift-detector)",
        headers: Mapping[str, str] | None = None,
        min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        max_total_retries: int = DEFAULT_MAX_TOTAL_RETRIES,
        backoff_initial_seconds: float = DEFAULT_BACKOFF_SECONDS,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = str(base_url).rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        self._headers: dict[str, str] = {
            "accept": "application/json",
            "user-agent": user_agent,
            **dict(headers or {}),
        }
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self._timeout,
            limits=self._limits,
            headers=self._headers,
        )
        self._min_interval_seconds = float(min_request_interval_seconds)
        self._last_request_monotonic = 0.0
        self._max_total_retries = max(1, max_total_retries)
        self._backoff_initial = max(backoff_initial_seconds, 1e-3)
        self._backoff_factor = max(backoff_factor, 1.0)
        self._backoff_cap = max(backoff_cap_seconds, self._backoff_initial)

        if self._min_interval_seconds >= (self._backoff_initial * self._max_total_retries):
            logger.debug(
                (
                    "CTIS pacing interval (%.3fs) dominates retry budget; "
                    "callers may observe long waits."
                ),
                self._min_interval_seconds,
            )

    def close(self) -> None:
        """Dispose the underlying ``httpx`` client only if constructed here."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CtisPublicClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):  # pragma: no cover - best-effort cleanup
            self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_monotonic
        deficit = self._min_interval_seconds - elapsed
        if deficit > 0:
            _sleep_respectfully(deficit)
        self._last_request_monotonic = time.monotonic()

    def _next_backoff_sleep(self, attempt: int, *, jitter: random.Random | None = None) -> float:
        rng = jitter or random
        backoff = min(
            self._backoff_initial * (self._backoff_factor**attempt),
            self._backoff_cap,
        )
        return rng.uniform(backoff / 4, backoff)

    def _perform_request(
        self,
        *,
        method: str,
        url: str,
        json_payload: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        last_transport_error: CtisPublicApiError | None = None

        for attempt in range(self._max_total_retries):
            self._throttle()
            try:
                response = self._client.request(method, url, json=json_payload)
            except httpx.TimeoutException as exc:
                request_url = str(exc.request.url)
                max_read = getattr(self._timeout, "read", None)
                timeout_hint = (
                    float(max_read) if max_read is not None else float(DEFAULT_TIMEOUT_SECONDS)
                )
                msg = (
                    f"Request timed out ({timeout_hint:.1f}s read budget)"
                    f" for {method} {request_url}"
                )
                logger.warning(
                    "%s (attempt %s/%s)",
                    msg,
                    attempt + 1,
                    self._max_total_retries,
                )
                last_transport_error = CtisTimeoutError(
                    msg,
                    url=request_url,
                    timeout_seconds=timeout_hint,
                )
                if attempt >= self._max_total_retries - 1:
                    raise last_transport_error from exc
                _sleep_respectfully(self._next_backoff_sleep(attempt))
                continue
            except httpx.RequestError as exc:
                request_url = url
                req = getattr(exc, "request", None)
                if req is not None and req.url is not None:
                    request_url = str(req.url)
                msg = f"Transport error calling {method} {request_url}: {exc}"
                logger.warning(
                    "%s (attempt %s/%s)",
                    msg,
                    attempt + 1,
                    self._max_total_retries,
                )
                last_transport_error = CtisTransportError(msg, url=request_url)
                if attempt >= self._max_total_retries - 1:
                    raise last_transport_error from exc
                _sleep_respectfully(self._next_backoff_sleep(attempt))
                continue

            retry_after_header = response.headers.get("Retry-After")
            retry_sleep: float | None = None
            if retry_after_header:
                retry_sleep = _parse_retry_after_seconds(retry_after_header)

            if response.status_code == 429:
                body_preview = _json_preview(response.text or "")
                logger.warning(
                    "Rate limited by CTIS (%s); retry_after=%s attempt=%s/%s",
                    url,
                    retry_after_header,
                    attempt + 1,
                    self._max_total_retries,
                )
                if attempt >= self._max_total_retries - 1:
                    raise CtisRateLimitError(
                        f"Too many requests {method} {url}: {body_preview}",
                        url=url,
                        status_code=response.status_code,
                        body_preview=body_preview,
                    )
                wait = retry_sleep if retry_sleep is not None else self._next_backoff_sleep(attempt)
                _sleep_respectfully(wait)
                continue

            if (
                response.status_code in _HTTP_RETRY_STATUSES
                and attempt < self._max_total_retries - 1
            ):
                body_preview = _json_preview(response.text or "")
                logger.warning(
                    "Retryable HTTP %s from CTIS (%s): %s",
                    response.status_code,
                    url,
                    body_preview,
                )
                wait = retry_sleep if retry_sleep is not None else self._next_backoff_sleep(attempt)
                _sleep_respectfully(wait)
                continue

            return response

        if last_transport_error is not None:
            raise last_transport_error
        raise CtisPublicApiError("Unexpected empty retry loop", url=url)

    @staticmethod
    def _raise_for_status(*, method: str, url: str, response: httpx.Response) -> None:
        if response.is_success:
            return
        preview = _json_preview(response.text or "")
        if response.status_code == 429:
            raise CtisRateLimitError(
                f"HTTP {response.status_code} for {method} {url}: {preview}",
                url=url,
                status_code=response.status_code,
                body_preview=preview,
            )
        raise CtisHttpResponseError(
            f"HTTP {response.status_code} for {method} {url}: {preview}",
            url=url,
            status_code=response.status_code,
            body_preview=preview,
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request, parse JSON, and map transport/timeout errors."""

        normalized = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        response = self._perform_request(method=method, url=normalized, json_payload=json_payload)
        self._raise_for_status(method=method, url=normalized, response=response)

        if response.status_code == 204 or not (response.content or b""):
            return None

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            preview = _json_preview(response.text or "")
            log_unexpected_error(logger, f"CTIS JSON decode failed ({normalized})")
            raise CtisMalformedJsonError(
                f"Invalid JSON from {normalized}: {exc}",
                url=normalized,
                preview=preview,
            ) from exc

    def search_trials(
        self,
        payload: TrialSearchPayload | None = None,
    ) -> TrialSearchResponse:
        """POST ``/search`` and validate the envelope.

        Respectful throttling and retries are enforced by :meth:`_perform_request`.

        Arguments:
            payload: Search/filter/sort model; defaults to newest decision dates via sort defaults.

        Returns:
            Parsed :class:`TrialSearchResponse`.

        Raises:
            CtisPublicApiError: family of subclasses for timeouts, transports, parsing, HTTP issues.
        """

        body = payload or TrialSearchPayload()
        raw = self._request_json(
            method="POST",
            path="search",
            json_payload=body.model_dump(by_alias=True, exclude_none=True),
        )
        if not isinstance(raw, dict):
            msg = "CTIS search response must be an object"
            raise CtisMalformedJsonError(
                msg,
                url=f"{self._base_url}/search",
                preview=str(type(raw).__name__),
            )
        try:
            return TrialSearchResponse.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - wrap pydantic diagnostics
            log_unexpected_error(logger, "TrialSearchResponse validation failed")
            preview = _json_preview(json.dumps(raw))
            raise CtisMalformedJsonError(
                "Search response JSON did not match expected schema.",
                url=f"{self._base_url}/search",
                preview=preview,
            ) from exc

    def get_full_trial(self, euct_number: str) -> TrialFullRecord:
        """GET ``/retrieve/{euct_number}``.

        Leading and trailing whitespace is trimmed. Pass the canonical EUCT code such as
        ``2024-518143-38-00``.

        Arguments:
            euct_number: EU clinical trial identifier (path segment suffix).

        Returns:
            Parsed :class:`TrialFullRecord` retaining unknown top-level extras.

        Raises:
            CtisPublicApiError: on transport/timeouts/non-success HTTP/non-JSON bodies.
        """

        sanitized = euct_number.strip().strip("/")
        if not sanitized:
            raise ValueError("euct_number must be a non-empty string")

        path = f"retrieve/{sanitized}"
        raw = self._request_json(method="GET", path=path)
        if not isinstance(raw, dict):
            msg = "CTIS retrieve response must be an object"
            raise CtisMalformedJsonError(
                msg,
                url=f"{self._base_url}/{path}",
                preview=str(type(raw).__name__),
            )

        try:
            record = TrialFullRecord.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - wrap pydantic diagnostics
            log_unexpected_error(logger, f"TrialFullRecord validation failed for {sanitized}")
            preview = _json_preview(json.dumps(raw))
            raise CtisMalformedJsonError(
                "Retrieve JSON did not match minimum schema expectations.",
                url=f"{self._base_url}/{path}",
                preview=preview,
            ) from exc

        logger.info("Fetched CTIS detail for ctNumber=%s", record.ct_number)
        return record


_DEFAULT_CLIENT_SINGLETON: CtisPublicClient | None = None


def public_client_singleton(
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
) -> CtisPublicClient:
    """Shared process-wide synchronous client reused by façade helpers."""

    global _DEFAULT_CLIENT_SINGLETON
    if _DEFAULT_CLIENT_SINGLETON is None:
        _DEFAULT_CLIENT_SINGLETON = CtisPublicClient(
            timeout_seconds=timeout_seconds,
            min_request_interval_seconds=min_interval_seconds,
        )
        logger.debug("Initialized CtisPublicClient singleton at %s", CTIS_PUBLIC_API_BASE_URL)
    return _DEFAULT_CLIENT_SINGLETON


class CTISAPIClient(CtisPublicClient):
    """Backwards-compatible entry point matching the legacy constructor surface.

    The official host is baked into :data:`CTIS_PUBLIC_API_BASE_URL`; the ``base_url``
    positional argument overrides it when migrating older configs that wrongly pointed elsewhere.
    Bearer tokens are not required today but forwarded if provided.

    Prefer :func:`~ctis_drift.core.ctis_api.search_trials` and
    :func:`~ctis_drift.core.ctis_api.get_full_trial`.
    """

    def __init__(
        self,
        base_url: str | HttpUrl | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        token: str | None = None,
        session: object | None = None,
        min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        http_client: httpx.Client | None = None,
    ) -> None:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resolved_base = CTIS_PUBLIC_API_BASE_URL if base_url is None else base_url

        super().__init__(
            base_url=resolved_base,
            timeout_seconds=timeout_seconds,
            headers=headers,
            min_request_interval_seconds=min_request_interval_seconds,
            client=http_client,
        )
        del session

    def health(self, *, page_size: int = 1) -> Mapping[str, Any]:
        """Lightweight readiness probe issuing a miniature search."""

        trimmed = max(1, min(page_size, 20))
        payload = TrialSearchPayload(pagination=SearchPagination(page=1, size=trimmed))
        summary = self.search_trials(payload)
        return {
            "status": "ok",
            "api": str(self._base_url),
            "show_warning": summary.show_warning,
            "pagination": summary.pagination.model_dump(by_alias=True),
            "hits_returned": len(summary.data),
        }
