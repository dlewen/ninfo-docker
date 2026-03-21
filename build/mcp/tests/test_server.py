"""
Tests for ninfo_mcp.server — auth middleware, rate limiter, and server config.

@decision DEC-AUTH-002
@title Test DjangoTokenAuthMiddleware with httpx mock and TTL cache
@status accepted
@rationale DjangoTokenAuthMiddleware makes HTTP calls to Django /api/me/.
httpx is mocked because Django is an external service boundary — there is no
in-process Django instance available in this package's test environment.
The mock-exempt annotations below document exactly which boundaries are mocked.
RateLimitMiddleware and cache logic are tested against the real implementation
with no mocking.
"""

# @mock-exempt: httpx.AsyncClient — external HTTP boundary (Django /api/me/ endpoint).
# There is no in-process Django available in the ninfo-mcp package tests.
# The real integration is covered by the django-ninfo test suite (test_user_info.py).

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ninfo_mcp.server import DjangoTokenAuthMiddleware, RateLimitMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware_context(username=None):
    """Build a minimal MiddlewareContext-like object with fastmcp_context state."""
    state = {}
    if username:
        state["username"] = username

    ctx = MagicMock()
    ctx.get_state = lambda key: state.get(key)
    ctx.set_state = lambda key, val: state.update({key: val})

    mc = MagicMock()
    mc.fastmcp_context = ctx
    return mc


async def _call_next(ctx):
    return "ok"


# ---------------------------------------------------------------------------
# DjangoTokenAuthMiddleware — cache logic (no mocks, pure state machine)
# ---------------------------------------------------------------------------


class TestDjangoTokenAuthMiddlewareCacheLogic:
    """Unit-test the cache methods directly using real time.monotonic control."""

    def test_cache_miss_returns_none(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        assert m._get_cached("no-such-token") is None

    def test_cache_stores_and_retrieves(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        m._set_cached("tok1", "alice")
        assert m._get_cached("tok1") == "alice"

    def test_cache_expires_after_ttl(self, monkeypatch):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=60)
        now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)
        m._set_cached("tok-expire", "bob")
        assert m._get_cached("tok-expire") == "bob"

        monkeypatch.setattr(time, "monotonic", lambda: now + 61)
        assert m._get_cached("tok-expire") is None

    def test_expired_entry_is_removed_from_cache(self, monkeypatch):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=60)
        now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)
        m._set_cached("tok-stale", "carol")

        monkeypatch.setattr(time, "monotonic", lambda: now + 61)
        m._get_cached("tok-stale")  # triggers prune
        assert "tok-stale" not in m._cache

    def test_cache_not_yet_expired(self, monkeypatch):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        now = 5000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)
        m._set_cached("tok-live", "dave")
        monkeypatch.setattr(time, "monotonic", lambda: now + 299)
        assert m._get_cached("tok-live") == "dave"

    def test_multiple_users_cached_independently(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        m._set_cached("tok-a", "alice")
        m._set_cached("tok-b", "bob")
        assert m._get_cached("tok-a") == "alice"
        assert m._get_cached("tok-b") == "bob"


# ---------------------------------------------------------------------------
# DjangoTokenAuthMiddleware — _validate_token HTTP calls
# (httpx mocked — external boundary, see @mock-exempt at top of file)
# ---------------------------------------------------------------------------


class TestDjangoTokenAuthMiddlewareValidation:
    @pytest.mark.asyncio
    async def test_valid_token_returns_username(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"username": "alice", "email": "alice@example.com"}

        with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            username = await m._validate_token("good-token")

        assert username == "alice"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_tool_error(self):
        from fastmcp.exceptions import ToolError

        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ToolError, match="invalid or expired token"):
                await m._validate_token("bad-token")

    @pytest.mark.asyncio
    async def test_forbidden_token_raises_tool_error(self):
        from fastmcp.exceptions import ToolError

        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ToolError, match="invalid or expired token"):
                await m._validate_token("forbidden-token")

    @pytest.mark.asyncio
    async def test_network_error_raises_tool_error(self):
        import httpx
        from fastmcp.exceptions import ToolError

        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)

        with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ToolError, match="auth service unavailable"):
                await m._validate_token("any-token")

    @pytest.mark.asyncio
    async def test_url_constructed_with_trailing_slash_stripped(self):
        """django_url with trailing slash must not produce double slash."""
        m = DjangoTokenAuthMiddleware("http://django:8000/", token_ttl=300)
        assert m._django_url == "http://django:8000"

    @pytest.mark.asyncio
    async def test_authorization_header_sent_as_token(self):
        """Validates that Authorization: Token <value> header is sent (not Bearer)."""
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"username": "hank", "email": "h@example.com"}

        with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await m._validate_token("my-token")

            call_kwargs = mock_client.get.call_args
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Token my-token"


# ---------------------------------------------------------------------------
# DjangoTokenAuthMiddleware — on_request flow
# ---------------------------------------------------------------------------


class TestDjangoTokenAuthMiddlewareOnRequest:
    @pytest.mark.asyncio
    async def test_missing_auth_header_raises_tool_error(self):
        from fastmcp.exceptions import ToolError

        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        ctx = _make_middleware_context()

        with patch("ninfo_mcp.server.get_http_headers", return_value={}):
            with pytest.raises(ToolError, match="missing or invalid"):
                await m.on_request(ctx, _call_next)

    @pytest.mark.asyncio
    async def test_non_bearer_header_raises_tool_error(self):
        from fastmcp.exceptions import ToolError

        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        ctx = _make_middleware_context()

        with patch(
            "ninfo_mcp.server.get_http_headers",
            return_value={"authorization": "Basic abc123"},
        ):
            with pytest.raises(ToolError, match="missing or invalid"):
                await m.on_request(ctx, _call_next)

    @pytest.mark.asyncio
    async def test_cached_token_skips_http_call(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        m._set_cached("cached-tok", "frank")
        ctx = _make_middleware_context()

        with patch("ninfo_mcp.server.get_http_headers", return_value={"authorization": "Bearer cached-tok"}):
            with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_http:
                result = await m.on_request(ctx, _call_next)

        mock_http.assert_not_called()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_uncached_token_calls_validate_and_caches(self):
        m = DjangoTokenAuthMiddleware("http://django:8000", token_ttl=300)
        ctx = _make_middleware_context()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"username": "grace", "email": "g@example.com"}

        with patch("ninfo_mcp.server.get_http_headers", return_value={"authorization": "Bearer fresh-tok"}):
            with patch("ninfo_mcp.server.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await m.on_request(ctx, _call_next)

        assert m._get_cached("fresh-tok") == "grace"
        assert result == "ok"


# ---------------------------------------------------------------------------
# RateLimitMiddleware (no mocks — pure in-memory state)
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_requests_within_limit_pass(self):
        m = RateLimitMiddleware(limit=5)
        ctx = _make_middleware_context(username="henry")

        for _ in range(5):
            result = await m.on_request(ctx, _call_next)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_request_exceeding_limit_raises_tool_error(self):
        from fastmcp.exceptions import ToolError

        m = RateLimitMiddleware(limit=3)
        ctx = _make_middleware_context(username="ivan")

        for _ in range(3):
            await m.on_request(ctx, _call_next)

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await m.on_request(ctx, _call_next)

    @pytest.mark.asyncio
    async def test_no_username_skips_rate_limit(self):
        m = RateLimitMiddleware(limit=1)
        ctx = _make_middleware_context()  # no username

        for _ in range(3):
            result = await m.on_request(ctx, _call_next)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_old_timestamps_pruned_outside_window(self, monkeypatch):
        m = RateLimitMiddleware(limit=2)
        ctx = _make_middleware_context(username="judy")

        now = 10000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)
        await m.on_request(ctx, _call_next)
        await m.on_request(ctx, _call_next)

        # Advance past 1 hour — old timestamps pruned
        monkeypatch.setattr(time, "monotonic", lambda: now + 3601)
        result = await m.on_request(ctx, _call_next)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_rate_limit_is_per_user(self):
        m = RateLimitMiddleware(limit=1)
        ctx_a = _make_middleware_context(username="userA")
        ctx_b = _make_middleware_context(username="userB")

        await m.on_request(ctx_a, _call_next)
        # userA is at limit; userB should still pass
        result = await m.on_request(ctx_b, _call_next)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_error_message_includes_limit(self):
        from fastmcp.exceptions import ToolError

        m = RateLimitMiddleware(limit=2)
        ctx = _make_middleware_context(username="ken")

        await m.on_request(ctx, _call_next)
        await m.on_request(ctx, _call_next)

        with pytest.raises(ToolError, match="2 requests/hour"):
            await m.on_request(ctx, _call_next)
