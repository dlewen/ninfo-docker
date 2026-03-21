"""ninfo MCP Server -- exposes ninfo plugin queries via MCP protocol over HTTP.

@decision DEC-FRAMEWORK-001
@title FastMCP with streamable HTTP transport
@status accepted
@rationale FastMCP provides simpler API than raw MCP SDK with built-in HTTP
transport, native middleware, and @mcp.tool decorator for dynamic tool
registration. Single ninfo_query tool wraps Ninfo.get_info_text() and
Ninfo.get_info_iter() for plugin-specific and all-plugin queries respectively.

@decision DEC-AUTH-001
@title Django /api/me/ token validation with in-memory TTL cache
@status accepted
@rationale MCP server validates DRF tokens by calling GET /api/me/ on the
Django container. A 200 response confirms the token is valid and returns the
username for audit logging. Results are cached in-memory for 5 minutes (TTL
configurable via NINFO_MCP_TOKEN_TTL_SECONDS) to avoid hammering Django on
every request. Invalid tokens are not cached. NINFO_DJANGO_URL env var points
to the Django container; default is http://ninfo-www:8000.
"""

import logging
import os
import time
from collections import defaultdict

import httpx
from fastmcp import FastMCP, Context
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError
from ninfo import Ninfo

log = logging.getLogger("ninfo_mcp")


# --- Auth Middleware ---


class DjangoTokenAuthMiddleware(Middleware):
    """Validates Bearer tokens against Django's /api/me/ endpoint.

    Tokens are cached in-memory for TOKEN_TTL seconds to reduce round-trips
    to Django. Invalid tokens are never cached so that revocations take
    effect immediately.

    @decision DEC-AUTH-001
    @title Django /api/me/ token validation with in-memory TTL cache
    @status accepted
    @rationale See module docstring.
    """

    def __init__(
        self,
        django_url: str,
        token_ttl: int = 300,
    ):
        self._django_url = django_url.rstrip("/")
        self._token_ttl = token_ttl
        # cache: token -> (username, expiry_timestamp)
        self._cache: dict[str, tuple[str, float]] = {}
        log.info(
            "DjangoTokenAuthMiddleware: validating against %s/api/me/ (TTL=%ds)",
            self._django_url,
            self._token_ttl,
        )

    def _get_cached(self, token: str) -> str | None:
        entry = self._cache.get(token)
        if entry is None:
            return None
        username, expiry = entry
        if time.monotonic() > expiry:
            del self._cache[token]
            return None
        return username

    def _set_cached(self, token: str, username: str) -> None:
        self._cache[token] = (username, time.monotonic() + self._token_ttl)

    async def _validate_token(self, token: str) -> str:
        """Call Django /api/me/ and return the username, or raise ToolError."""
        url = f"{self._django_url}/api/me/"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Token {token}"}
                )
        except httpx.RequestError as exc:
            log.error("Token validation request failed: %s", exc)
            raise ToolError("Access denied: auth service unavailable") from exc

        if resp.status_code == 200:
            data = resp.json()
            return data["username"]
        elif resp.status_code in (401, 403):
            raise ToolError("Access denied: invalid or expired token")
        else:
            log.error(
                "Unexpected status from /api/me/: %d %s", resp.status_code, resp.text
            )
            raise ToolError("Access denied: auth service error")

    async def on_request(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        auth_header = headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            raise ToolError("Access denied: missing or invalid Authorization header")

        token = auth_header.removeprefix("Bearer ").strip()

        # Check cache first
        username = self._get_cached(token)
        if username is None:
            username = await self._validate_token(token)
            self._set_cached(token, username)

        # Store username in context for logging / rate limiting
        if context.fastmcp_context:
            context.fastmcp_context.set_state("username", username)
        log.info("Authenticated request from user: %s", username)

        return await call_next(context)


# --- Rate Limiting Middleware ---


class RateLimitMiddleware(Middleware):
    """Simple in-memory per-user rate limiter (sliding window, hourly).

    @decision DEC-RATELIMIT-001
    @title In-memory per-user sliding window rate limiter
    @status accepted
    @rationale Single-instance deployment; no need for Redis. Timestamps list
    per user, prune entries older than 1 hour before checking. Configurable
    via NINFO_MCP_RATE_LIMIT env var (default 60 req/hour). Rate limit runs
    after auth so username is available in context state.
    """

    def __init__(self, limit: int = 60):
        self._limit = limit
        # username -> list of request timestamps (monotonic)
        self._windows: dict[str, list[float]] = defaultdict(list)
        log.info("RateLimitMiddleware: %d requests/hour per user", self._limit)

    async def on_request(self, context: MiddlewareContext, call_next):
        username = None
        if context.fastmcp_context:
            username = context.fastmcp_context.get_state("username")

        if username:
            now = time.monotonic()
            window = self._windows[username]
            # Prune timestamps older than 1 hour
            cutoff = now - 3600
            self._windows[username] = [t for t in window if t > cutoff]
            if len(self._windows[username]) >= self._limit:
                log.warning("Rate limit exceeded for user: %s", username)
                raise ToolError(
                    f"Rate limit exceeded: {self._limit} requests/hour"
                )
            self._windows[username].append(now)

        return await call_next(context)


# --- Server Setup ---

NINFO_DJANGO_URL = os.environ.get("NINFO_DJANGO_URL", "http://ninfo-www:8000")
TOKEN_TTL = int(os.environ.get("NINFO_MCP_TOKEN_TTL_SECONDS", "300"))
RATE_LIMIT = int(os.environ.get("NINFO_MCP_RATE_LIMIT", "60"))

mcp = FastMCP(
    name="ninfo-mcp",
    instructions=(
        "Query threat intelligence sources using ninfo plugins. "
        "Supports IPs, domains, hashes, hostnames, URLs, and more. "
        "Use the ninfo_query tool with a query string. Optionally specify "
        "a plugin name to target a specific source."
    ),
)
mcp.add_middleware(DjangoTokenAuthMiddleware(django_url=NINFO_DJANGO_URL, token_ttl=TOKEN_TTL))
mcp.add_middleware(RateLimitMiddleware(limit=RATE_LIMIT))



# --- Ninfo Lazy Init ---

# Lazy-initialized Ninfo instance
_ninfo: Ninfo | None = None


def _get_ninfo() -> Ninfo:
    """Lazy-init Ninfo instance on first use.

    @decision DEC-CONFIG-001
    @title Lazy Ninfo initialization
    @status accepted
    @rationale Ninfo reads ninfo.ini at init time. The ninfo.ini is
    volume-mounted at /app/ninfo.ini in Docker. Lazy init ensures the file
    exists and is fully written when Ninfo() is first called (at first
    request, not at import time).
    """
    global _ninfo
    if _ninfo is None:
        _ninfo = Ninfo()
        log.info(
            "Initialized ninfo with %d plugins: %s",
            len(_ninfo.plugin_modules),
            ", ".join(sorted(_ninfo.plugin_modules.keys())),
        )
    return _ninfo


# --- Tool ---


@mcp.tool
def ninfo_query(query: str, plugin: str | None = None) -> str:
    """Query threat intelligence sources for an IP, domain, hash, or other indicator.

    @decision DEC-TOOL-001
    @title Single ninfo_query tool
    @status accepted
    @rationale ninfo handles type detection and plugin routing internally.
    Single tool surface keeps the MCP interface simple. The MCP server
    imports ninfo directly (same Docker image, same ninfo.ini volume mount)
    and does NOT proxy queries through Django — this avoids double-hop latency
    and keeps ninfo.ini as the single source of plugin configuration.

    Args:
        query: The indicator to look up (IP address, domain, hash, hostname, URL, etc.).
               ninfo auto-detects the type.
        plugin: Optional plugin name to query a specific source (e.g. "shodan", "virustotal").
                When omitted, all compatible plugins are queried.

    Returns:
        Rendered text output from each plugin's Mako template.
    """
    n = _get_ninfo()

    if plugin:
        # Single plugin query
        if plugin not in n.plugin_modules:
            available = ", ".join(sorted(n.plugin_modules.keys()))
            return f"Error: Unknown plugin '{plugin}'. Available plugins: {available}"

        if not n.compatible_argument(plugin, query):
            return f"Error: Plugin '{plugin}' is not compatible with query '{query}'"

        try:
            text = n.get_info_text(plugin, query)
            if not text:
                return f"No results from plugin '{plugin}' for query '{query}'"

            p = n.get_plugin(plugin)
            return f"## {p.name}\n\n{text}"
        except Exception as e:
            log.exception("Error querying plugin %s", plugin)
            return f"Error querying plugin '{plugin}': {e}"

    # All compatible plugins
    results = []
    for p, result in n.get_info_iter(query):
        try:
            text = p.render_template("text", query, result)
            if text:
                results.append(f"## {p.name}\n\n{text}")
        except Exception as e:
            log.exception("Error rendering plugin %s", p.name)
            results.append(f"## {p.name}\n\nError: {e}")

    if not results:
        return f"No compatible plugins found for query '{query}'"

    return "\n\n".join(results)


# --- Entry Point ---


def main():
    """Entry point -- run the ninfo MCP server over HTTP on port 8001."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    host = os.environ.get("NINFO_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("NINFO_MCP_PORT", "8001"))
    log.info("Starting ninfo-mcp on %s:%d", host, port)
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
