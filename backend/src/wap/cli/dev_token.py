"""Print an access token for a Keycloak dev-realm user. Development only.

Uses the password grant on the public `wap-web` client, which the dev realm
enables for this purpose; real clients use the authorization code flow.

    python -m wap.cli.dev_token north.admin
    curl -H "Authorization: Bearer $(python -m wap.cli.dev_token north.admin)" ...
"""

import sys

import httpx

from wap.config import get_settings

CLIENT_ID = "wap-web"
DEV_PASSWORD = "password"  # noqa: S105 - the dev realm's seeded password


def fetch_token(username: str, password: str = DEV_PASSWORD) -> str:
    issuer = get_settings().oidc_issuer.rstrip("/")
    with httpx.Client(timeout=10) as http:
        meta = http.get(f"{issuer}/.well-known/openid-configuration")
        meta.raise_for_status()
        resp = http.post(
            str(meta.json()["token_endpoint"]),
            data={
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "username": username,
                "password": password,
                "scope": "openid",
            },
        )
    if resp.status_code != 200:
        raise SystemExit(f"token request failed ({resp.status_code}): {resp.text}")
    return str(resp.json()["access_token"])


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit("usage: python -m wap.cli.dev_token <username>")
    print(fetch_token(argv[0]))


if __name__ == "__main__":
    main(sys.argv[1:])
