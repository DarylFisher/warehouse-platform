"""Tests that need no database."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from wap import __version__
from wap.api.main import create_app
from wap.api.sites import SiteIn
from wap.kernel.tenancy.context import is_valid_slug


@pytest.fixture
async def bare_client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.pool = None  # routes under test must not touch the database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_liveness(bare_client: AsyncClient) -> None:
    r = await bare_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


async def test_tenant_header_required(bare_client: AsyncClient) -> None:
    r = await bare_client.get("/api/sites")
    assert r.status_code == 400


@pytest.mark.parametrize(
    ("slug", "valid"),
    [
        ("demo-north", True),
        ("a", True),
        ("Demo", False),
        ("-leading", False),
        ("trailing-", False),
        ("bad_char", False),
        ("x" * 64, False),
        ("'; DROP TABLE kernel.tenants; --", False),
    ],
)
def test_slug_validation(slug: str, valid: bool) -> None:
    assert is_valid_slug(slug) is valid


def test_site_code_must_be_upper_case() -> None:
    with pytest.raises(ValidationError):
        SiteIn(code="ndc1", name="lower case code")
    assert SiteIn(code="NDC-1", name="ok").code == "NDC-1"
