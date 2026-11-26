"""Token verification and tenant mapping. No database or identity provider needed."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
import jwt
import pytest
from auth_support import (
    TEST_AUDIENCE,
    TEST_KEY,
    jwks_for_tests,
    make_verifier,
    mint_token,
    public_jwk,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from wap.api.main import create_app
from wap.kernel.identity import (
    IdentityProviderUnavailableError,
    InvalidTokenError,
    JwksCache,
    TokenVerifier,
    tenant_slugs_from_groups,
)

GROUP_CASES: list[tuple[object, set[str]]] = [
    (["tenant-demo-north"], {"demo-north"}),
    (["/tenant-demo-north", "/tenant-demo-south"], {"demo-north", "demo-south"}),
    (["admins", "tenant-", "xtenant-a"], set()),
    ("tenant-demo-north", set()),  # not a list
    ([1, None, "tenant-ok"], {"ok"}),
    (None, set()),
]


@pytest.mark.parametrize(("groups", "expected"), GROUP_CASES)
def test_tenant_slugs_from_groups(groups: object, expected: set[str]) -> None:
    assert tenant_slugs_from_groups(groups, "tenant-") == expected


async def test_valid_token_gives_principal() -> None:
    token = mint_token(
        groups=["tenant-demo-north", "other"], sub="abc", email="a@example.com", name="A"
    )
    p = await make_verifier().verify(token)
    assert (p.subject, p.email, p.name) == ("abc", "a@example.com", "A")
    assert p.tenant_slugs == {"demo-north"}


async def test_audience_can_be_a_list() -> None:
    token = mint_token(aud=["account", TEST_AUDIENCE])
    await make_verifier().verify(token)


def _other_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: mint_token(expires_in=-120), id="expired"),
        pytest.param(lambda: mint_token(iss="https://evil.test/"), id="wrong-issuer"),
        pytest.param(lambda: mint_token(aud="wap-web"), id="wrong-audience"),
        pytest.param(lambda: mint_token(key=_other_key()), id="bad-signature"),
        pytest.param(lambda: mint_token(kid="unknown-kid"), id="unknown-key"),
        pytest.param(lambda: "not-a-jwt", id="malformed"),
        pytest.param(
            lambda: jwt.encode({"sub": "x"}, "s" * 32, algorithm="HS256", headers={"kid": "k"}),
            id="hmac",
        ),
        pytest.param(
            lambda: jwt.encode({"sub": "x"}, "", algorithm="none", headers={"kid": "k"}),
            id="alg-none",
        ),
    ],
)
async def test_bad_tokens_are_rejected(token: Any) -> None:
    with pytest.raises(InvalidTokenError):
        await make_verifier().verify(token())


async def test_missing_required_claim_is_rejected() -> None:
    now = 1_900_000_000
    token = jwt.encode(
        {"iss": "https://issuer.test/realms/wap", "aud": TEST_AUDIENCE, "exp": now, "iat": now},
        TEST_KEY,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )  # no "sub"
    with pytest.raises(InvalidTokenError):
        await make_verifier().verify(token)


async def test_rotated_key_is_fetched_once_then_cached() -> None:
    new_key = _other_key()
    keysets: list[Mapping[str, Any]] = [
        jwks_for_tests(),
        {"keys": [*jwks_for_tests()["keys"], public_jwk(new_key, "k2")]},
    ]
    calls = 0

    async def fetch() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return keysets[min(calls, 2) - 1]

    verifier = TokenVerifier(
        issuer="https://issuer.test/realms/wap",
        audience=TEST_AUDIENCE,
        jwks=JwksCache(fetch, min_refresh_interval=0),
    )
    await verifier.verify(mint_token())
    await verifier.verify(mint_token(key=new_key, kid="k2"))
    await verifier.verify(mint_token(key=new_key, kid="k2"))
    assert calls == 2


async def test_unknown_kids_do_not_refetch_within_the_refresh_interval() -> None:
    calls = 0

    async def fetch() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return jwks_for_tests()

    verifier = TokenVerifier(
        issuer="https://issuer.test/realms/wap",
        audience=TEST_AUDIENCE,
        jwks=JwksCache(fetch, min_refresh_interval=3600),
    )
    for _ in range(5):
        with pytest.raises(InvalidTokenError):
            await verifier.verify(mint_token(kid="nope"))
    assert calls == 1


async def test_provider_down_with_no_cached_keys_is_unavailable() -> None:
    async def fetch() -> Mapping[str, Any]:
        raise httpx.ConnectError("down")

    verifier = TokenVerifier(
        issuer="https://issuer.test/realms/wap", audience=TEST_AUDIENCE, jwks=JwksCache(fetch)
    )
    with pytest.raises(IdentityProviderUnavailableError):
        await verifier.verify(mint_token())


async def test_provider_outage_keeps_cached_keys_and_backs_off() -> None:
    calls = 0

    async def fetch() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ConnectError("down")
        return jwks_for_tests()

    # ttl=0: every request finds the keys stale and wants to refresh.
    verifier = TokenVerifier(
        issuer="https://issuer.test/realms/wap",
        audience=TEST_AUDIENCE,
        jwks=JwksCache(fetch, ttl=0, min_refresh_interval=3600),
    )
    for _ in range(5):
        await verifier.verify(mint_token())
    assert calls == 2  # the first fetch, then one failed retry; no retry per request


async def test_concurrent_requests_share_one_fetch() -> None:
    calls = 0

    async def fetch() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return jwks_for_tests()

    verifier = TokenVerifier(
        issuer="https://issuer.test/realms/wap", audience=TEST_AUDIENCE, jwks=JwksCache(fetch)
    )
    await asyncio.gather(*(verifier.verify(mint_token()) for _ in range(10)))
    assert calls == 1


@pytest.fixture
async def api() -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.pool = None  # these requests are rejected before any database access
    app.state.verifier = make_verifier()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_me_returns_principal(api: AsyncClient) -> None:
    token = mint_token(groups=["tenant-b", "tenant-a"], sub="u1", email="u@example.com")
    r = await api.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {
        "subject": "u1",
        "email": "u@example.com",
        "name": None,
        "tenants": ["a", "b"],
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer not-a-jwt"},
        {"X-Tenant": "demo-north"},  # the old development header grants nothing
    ],
)
async def test_requests_without_a_valid_token_are_401(
    api: AsyncClient, headers: dict[str, str]
) -> None:
    for path in ("/api/me", "/api/sites"):
        r = await api.get(path, headers=headers)
        assert r.status_code == 401, (path, r.text)
        assert r.headers["www-authenticate"] == "Bearer"


async def test_token_without_tenant_groups_is_403(api: AsyncClient) -> None:
    token = mint_token(groups=["admins"])
    r = await api.get("/api/sites", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
