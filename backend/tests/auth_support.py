"""Signed test tokens, so tests need no identity provider."""

import time
import uuid
from collections.abc import Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from wap.cli.seed import DEV_USERS
from wap.kernel.identity import JwksCache, TokenVerifier

TEST_ISSUER = "https://issuer.test/realms/wap"
TEST_AUDIENCE = "wap-api"
TEST_KID = "test-key-1"
TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


def jwks_for_tests() -> dict[str, Any]:
    return {"keys": [public_jwk(TEST_KEY, TEST_KID)]}


def make_verifier(jwks: Mapping[str, Any] | None = None) -> TokenVerifier:
    keys = jwks or jwks_for_tests()

    async def fetch() -> Mapping[str, Any]:
        return keys

    return TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE, jwks=JwksCache(fetch))


def mint_token(
    *,
    groups: list[str] | None = None,
    sub: str = "user-1",
    key: rsa.RSAPrivateKey = TEST_KEY,
    kid: str = TEST_KID,
    alg: str = "RS256",
    expires_in: int = 300,
    **claims: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": sub,
        "iat": now,
        "exp": now + expires_in,
        "jti": str(uuid.uuid4()),
        "groups": groups if groups is not None else [],
        **claims,
    }
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid})


def bearer_for(*slugs: str, sub: str | None = None, **claims: Any) -> dict[str, str]:
    """Authorization header for a user in the given tenants' groups.

    Unless ``sub`` names a seeded user, this user has no roles yet: the first
    request provisions them with none.
    """
    subject = sub or f"user-{'-'.join(slugs)}"
    token = mint_token(groups=[f"tenant-{s}" for s in slugs], sub=subject, **claims)
    return {"Authorization": f"Bearer {token}"}


def bearer_as(username: str) -> dict[str, str]:
    """Authorization header for a seeded dev user (see wap.cli.seed.DEV_USERS)."""
    subject, email, name, grants = DEV_USERS[username]
    token = mint_token(
        groups=[f"tenant-{slug}" for slug in grants], sub=subject, email=email, name=name
    )
    return {"Authorization": f"Bearer {token}"}
