"""Google Ads Keyword Planner MCP server.

Tools
-----
- keyword_ideas:        seed keywords and/or a URL -> related keyword ideas with metrics
- keyword_metrics:      exact keywords -> historical volume, competition, bid range
- list_locations:       search geo target constants (country/region/city) -> IDs
- list_languages:       common language constant IDs

Auth is via environment variables (see .env.example). Runs over stdio by default,
or streamable HTTP (for Railway etc.) with MCP_TRANSPORT=http.
"""

from __future__ import annotations

import functools
import os
from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from mcp.server.fastmcp import FastMCP

try:  # optional, only needed for local development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

mcp = FastMCP(
    "google-ads-keyword-planner",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
)

# Language constants are stable IDs: https://developers.google.com/google-ads/api/data/codes-formats#languages
LANGUAGES = {
    "english": 1000,
    "german": 1001,
    "french": 1002,
    "spanish": 1003,
    "italian": 1004,
    "japanese": 1005,
    "danish": 1009,
    "dutch": 1010,
    "finnish": 1011,
    "korean": 1012,
    "norwegian": 1013,
    "portuguese": 1014,
    "swedish": 1015,
    "chinese_simplified": 1017,
    "chinese_traditional": 1018,
    "arabic": 1019,
    "russian": 1031,
    "hindi": 1023,
}

# A few common geo targets so the common case needs no lookup.
COMMON_LOCATIONS = {
    "united states": 2840,
    "canada": 2124,
    "united kingdom": 2826,
    "australia": 2036,
    "germany": 2276,
    "france": 2250,
    "india": 2356,
    "british columbia": 20102,  # verify with list_locations if in doubt
}

_client: GoogleAdsClient | None = None


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import PlainTextResponse

    return PlainTextResponse("ok")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_client() -> GoogleAdsClient:
    global _client
    if _client is None:
        config: dict[str, Any] = {
            "developer_token": _required("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": _required("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": _required("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": _required("GOOGLE_ADS_REFRESH_TOKEN"),
            "use_proto_plus": True,
        }
        login = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        if login:
            config["login_customer_id"] = login.replace("-", "")
        _client = GoogleAdsClient.load_from_dict(config)
    return _client


def _customer_id() -> str:
    return _required("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")


def _language_resource(client: GoogleAdsClient, language: str | int) -> str:
    if isinstance(language, int) or str(language).isdigit():
        lang_id = int(language)
    else:
        key = str(language).strip().lower().replace(" ", "_")
        if key not in LANGUAGES:
            raise ValueError(
                f"Unknown language '{language}'. Known: {', '.join(sorted(LANGUAGES))} "
                "or pass a numeric language constant ID."
            )
        lang_id = LANGUAGES[key]
    return client.get_service("GoogleAdsService").language_constant_path(lang_id)


def _location_resources(client: GoogleAdsClient, locations: list[str | int]) -> list[str]:
    svc = client.get_service("GeoTargetConstantService")
    out = []
    for loc in locations:
        if isinstance(loc, int) or str(loc).isdigit():
            geo_id = int(loc)
        else:
            key = str(loc).strip().lower()
            if key not in COMMON_LOCATIONS:
                raise ValueError(
                    f"Unknown location '{loc}'. Use list_locations to find its ID, "
                    "then pass the numeric ID."
                )
            geo_id = COMMON_LOCATIONS[key]
        out.append(svc.geo_target_constant_path(geo_id))
    return out


def _network(client: GoogleAdsClient, include_partners: bool):
    enum = client.enums.KeywordPlanNetworkEnum
    return enum.GOOGLE_SEARCH_AND_PARTNERS if include_partners else enum.GOOGLE_SEARCH


def _micros(value: int | None) -> float | None:
    return round(value / 1_000_000, 2) if value else None


def _format_metrics(metrics) -> dict[str, Any]:
    monthly = [
        {
            "year": m.year,
            "month": m.month.name,
            "searches": m.monthly_searches,
        }
        for m in metrics.monthly_search_volumes
    ]
    return {
        "avg_monthly_searches": metrics.avg_monthly_searches,
        "competition": metrics.competition.name,
        "competition_index": metrics.competition_index,
        "low_top_of_page_bid": _micros(metrics.low_top_of_page_bid_micros),
        "high_top_of_page_bid": _micros(metrics.high_top_of_page_bid_micros),
        "monthly_searches": monthly,
    }


def _wrap_errors(fn):
    """Turn GoogleAdsException into a readable error for the model."""

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GoogleAdsException as ex:
            details = "; ".join(
                f"{e.error_code}: {e.message}" for e in ex.failure.errors
            )
            raise RuntimeError(
                f"Google Ads API error (request {ex.request_id}): {details}"
            ) from None

    return inner


@mcp.tool()
@_wrap_errors
def keyword_ideas(
    keywords: list[str] | None = None,
    url: str | None = None,
    locations: list[str | int] | None = None,
    language: str | int = "english",
    include_partners: bool = False,
    limit: int = 50,
    include_adult: bool = False,
    sort_by: str = "volume",
) -> dict[str, Any]:
    """Generate keyword ideas from seed keywords and/or a page or site URL.

    Args:
        keywords: Seed keywords (up to 20). Optional if url is given.
        url: A page or site URL to mine for ideas. If keywords are also given,
            ideas come from both; set neither and the call fails.
        locations: Location names (e.g. "canada") or numeric geo target IDs.
            Defaults to United States. Use list_locations to find IDs.
        language: Language name (e.g. "english") or numeric language constant ID.
        include_partners: Include Google search partners network.
        limit: Max ideas to return (1-500), after sorting.
        include_adult: Include adult keyword ideas.
        sort_by: "volume" (default), "competition", or "alphabetical".
    """
    if not keywords and not url:
        raise ValueError("Provide keywords, a url, or both.")
    limit = max(1, min(limit, 500))

    client = _get_client()
    service = client.get_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordIdeasRequest")
    request.customer_id = _customer_id()
    request.language = _language_resource(client, language)
    request.geo_target_constants.extend(
        _location_resources(client, locations or ["united states"])
    )
    request.keyword_plan_network = _network(client, include_partners)
    request.include_adult_keywords = include_adult

    if keywords and url:
        request.keyword_and_url_seed.url = url
        request.keyword_and_url_seed.keywords.extend(keywords[:20])
    elif keywords:
        request.keyword_seed.keywords.extend(keywords[:20])
    else:
        request.url_seed.url = url

    results = []
    for idea in service.generate_keyword_ideas(request=request):
        row = {"keyword": idea.text, **_format_metrics(idea.keyword_idea_metrics)}
        results.append(row)

    if sort_by == "competition":
        results.sort(key=lambda r: r["competition_index"] or 0, reverse=True)
    elif sort_by == "alphabetical":
        results.sort(key=lambda r: r["keyword"])
    else:
        results.sort(key=lambda r: r["avg_monthly_searches"] or 0, reverse=True)

    return {
        "total_ideas": len(results),
        "returned": min(limit, len(results)),
        "ideas": results[:limit],
    }


@mcp.tool()
@_wrap_errors
def keyword_metrics(
    keywords: list[str],
    locations: list[str | int] | None = None,
    language: str | int = "english",
    include_partners: bool = False,
) -> dict[str, Any]:
    """Get historical search metrics for an exact list of keywords.

    Returns average monthly searches, competition, top-of-page bid range
    (in account currency), and 12 months of volume per keyword.

    Args:
        keywords: Keywords to look up (up to 200).
        locations: Location names or numeric geo target IDs. Defaults to United States.
        language: Language name or numeric language constant ID.
        include_partners: Include Google search partners network.
    """
    if not keywords:
        raise ValueError("Provide at least one keyword.")

    client = _get_client()
    service = client.get_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = _customer_id()
    request.keywords.extend(keywords[:200])
    request.language = _language_resource(client, language)
    request.geo_target_constants.extend(
        _location_resources(client, locations or ["united states"])
    )
    request.keyword_plan_network = _network(client, include_partners)

    response = service.generate_keyword_historical_metrics(request=request)
    results = []
    for r in response.results:
        results.append({"keyword": r.text, **_format_metrics(r.keyword_metrics)})
    return {"count": len(results), "keywords": results}


@mcp.tool()
@_wrap_errors
def list_locations(query: str, locale: str = "en", country_code: str = "US") -> dict[str, Any]:
    """Search geo target constants by name to get IDs for the locations parameter.

    Args:
        query: Place name, e.g. "Victoria" or "British Columbia".
        locale: Language for returned names.
        country_code: Two-letter country code to bias results.
    """
    client = _get_client()
    service = client.get_service("GeoTargetConstantService")
    request = client.get_type("SuggestGeoTargetConstantsRequest")
    request.locale = locale
    request.country_code = country_code
    request.location_names.names.append(query)

    response = service.suggest_geo_target_constants(request=request)
    matches = []
    for s in response.geo_target_constant_suggestions:
        g = s.geo_target_constant
        matches.append(
            {
                "id": g.id,
                "name": g.name,
                "canonical_name": g.canonical_name,
                "target_type": g.target_type,
                "country_code": g.country_code,
                "status": g.status.name,
            }
        )
    return {"matches": matches}


@mcp.tool()
def list_languages() -> dict[str, int]:
    """Common language names and their Google Ads language constant IDs."""
    return LANGUAGES


class _BearerAuth:
    """Minimal ASGI middleware: require 'Authorization: Bearer <MCP_AUTH_TOKEN>'."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != self.expected and scope["path"] != "/health":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        import uvicorn

        token = os.environ.get("MCP_AUTH_TOKEN")
        if not token:
            raise RuntimeError(
                "MCP_AUTH_TOKEN is required in HTTP mode so the endpoint isn't open "
                "to the internet. Set it to a long random string."
            )
        app = _BearerAuth(mcp.streamable_http_app(), token)
        uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
