"""OIDC access-token verification.

Provider-neutral on purpose: Keycloak locally, WorkOS in production, so only
standard OIDC is relied on (issuer, audience, JWKS). The tenant comes from the
token's ``groups`` claim, never from anything else the client sends.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

# Asymmetric algorithms only: "none" and HMAC (shared secret) are never accepted.
ALLOWED_ALGORITHMS = ("RS256", "PS256", "ES256")
REQUIRED_CLAIMS = ("exp", "iat", "iss", "aud", "sub")


class InvalidTokenError(Exception):
    """The token is missing, malformed, expired, or not ours. Maps to HTTP 401."""


class IdentityProviderUnavailableError(Exception):
    """The provider's signing keys could not be fetched. Maps to HTTP 503."""


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    email: str | None
    name: str | None
    tenant_slugs: frozenset[str]


def tenant_slugs_from_groups(groups: object, prefix: str) -> frozenset[str]:
    """``["tenant-demo-north", "other"]`` with prefix ``tenant-`` -> ``{"demo-north"}``.

    Accepts plain names and Keycloak full paths (``/tenant-demo-north``).
    """
    if not isinstance(groups, list):
        return frozenset()
    slugs: set[str] = set()
    for group in groups:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(group, str):
            continue
        name = group.rsplit("/", 1)[-1]
        if name.startswith(prefix) and len(name) > len(prefix):
            slugs.add(name.removeprefix(prefix))
    return frozenset(slugs)


JwksFetcher = Callable[[], Awaitable[Mapping[str, Any]]]


class JwksCache:
    """The provider's public keys, cached and refreshed.

    Keys are refetched after ``ttl`` seconds, and early when a token names a key
    id we have not seen (the provider rotated keys), but at most once every
    ``min_refresh_interval`` seconds so bad tokens can't hammer the provider.
    """

    def __init__(
        self,
        fetch: JwksFetcher,
        *,
        ttl: float = 3600,
        min_refresh_interval: float = 30,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._min_refresh_interval = min_refresh_interval
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK:
        now = time.monotonic()
        stale = self._fetched_at is None or now - self._fetched_at > self._ttl
        if stale or (kid not in self._keys and self._may_refresh(now)):
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise InvalidTokenError("unknown signing key")
        return key

    def _may_refresh(self, now: float) -> bool:
        return self._fetched_at is None or now - self._fetched_at >= self._min_refresh_interval

    async def _refresh(self) -> None:
        requested_at = time.monotonic()
        async with self._lock:
            if self._fetched_at is not None and self._fetched_at >= requested_at:
                return  # another request refreshed while this one waited
            try:
                data = await self._fetch()
            except (httpx.HTTPError, ValueError) as exc:
                if self._keys:
                    # Keep serving the keys we have; retry after the refresh interval
                    # rather than on every request while the provider is down.
                    self._fetched_at = time.monotonic() - self._ttl + self._min_refresh_interval
                    return
                raise IdentityProviderUnavailableError(str(exc)) from exc
            keys: dict[str, jwt.PyJWK] = {}
            for entry in data.get("keys", []):
                if not isinstance(entry, dict) or "kid" not in entry:
                    continue
                if entry.get("use", "sig") != "sig":
                    continue
                try:
                    keys[str(entry["kid"])] = jwt.PyJWK(entry)  # pyright: ignore[reportUnknownArgumentType]
                except jwt.PyJWKError:
                    continue  # an algorithm we don't support; skip that key
            self._keys = keys
            self._fetched_at = time.monotonic()


def http_jwks_fetcher(client: httpx.AsyncClient, issuer: str, jwks_url: str | None) -> JwksFetcher:
    """Fetch JWKS from ``jwks_url``, or discover it from the issuer's metadata."""

    async def fetch() -> Mapping[str, Any]:
        url = jwks_url
        if url is None:
            meta = await client.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
            meta.raise_for_status()
            url = str(meta.json()["jwks_uri"])
        resp = await client.get(url)
        resp.raise_for_status()
        body: Mapping[str, Any] = resp.json()
        return body

    return fetch


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks: JwksCache,
        tenant_group_prefix: str = "tenant-",
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self._jwks = jwks
        self._prefix = tenant_group_prefix
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc
        alg = header.get("alg")
        kid = header.get("kid")
        if alg not in ALLOWED_ALGORITHMS:
            raise InvalidTokenError("algorithm not allowed")
        if not isinstance(kid, str):
            raise InvalidTokenError("token has no key id")
        key = await self._jwks.get(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc
        email = claims.get("email")
        name = claims.get("name")
        return Principal(
            subject=str(claims["sub"]),
            email=email if isinstance(email, str) else None,
            name=name if isinstance(name, str) else None,
            tenant_slugs=tenant_slugs_from_groups(claims.get("groups"), self._prefix),
        )
