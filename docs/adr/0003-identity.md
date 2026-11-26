# ADR 0003: OIDC access tokens; tenant from group membership

- Status: accepted
- Date: 2026-11-26

## Decision

The API accepts only OIDC access tokens (`Authorization: Bearer`), verified
locally against the provider's published signing keys. Keycloak runs locally;
WorkOS is the production provider. The code uses plain OIDC only (issuer,
audience, JWKS), so the provider can change by configuration.

- **Checks:** signature against JWKS, `exp` and `iat` (30 s leeway), `iss` equal
  to `WAP_OIDC_ISSUER`, `aud` containing `WAP_OIDC_AUDIENCE` (`wap-api`), and a
  `sub`. Only asymmetric algorithms (RS256, PS256, ES256); never `none` or HMAC.
- **Access, not ID, tokens:** the `wap-api` audience is added to access tokens
  only, so an ID token is rejected by the audience check.
- **Keys:** cached for an hour and refetched early when a token names an unseen
  key id (rotation), at most once every 30 s. If the provider is down, cached
  keys keep working; with none cached, requests get 503.
- **Tenant:** comes only from the token's `groups` claim: membership in
  `tenant-<slug>` grants that tenant. One granted tenant is used directly. A
  user in several picks one per request with `X-Tenant`, which must name a
  granted tenant (403 otherwise); with several and no choice, 400. The header
  never grants access. The slug is then resolved as before; an unknown or
  suspended tenant is 403.
- **Errors:** no or invalid token is 401 with `WWW-Authenticate: Bearer`; the
  reason is logged, not returned.
- **Local issuer:** Keycloak's public hostname is fixed (`KC_HOSTNAME`), so
  tokens name the same issuer whether fetched from the host or from a container.
  The API container fetches keys over the Docker network (`WAP_OIDC_JWKS_URL`);
  elsewhere keys come from the issuer's discovery document.

## Considered

- Token introspection on every request: always current, but a provider round
  trip per request and an outage takes the API down with it.
- Tenant in a custom claim: simpler to read, but needs a provider-specific
  mapper. Groups work in Keycloak and WorkOS (directory groups) alike.
- Keeping the unauthenticated `X-Tenant` header behind a development flag:
  removed, so no configuration can turn it back on in production.

## Consequences

- Revoking access takes effect when the user's access token expires (5 minutes
  in the dev realm); keep production lifetimes short.
- Tests sign tokens with their own key, so CI needs no identity provider.
- Users and roles tables (next M1 step) key users by `iss` + `sub`.
- Badge or PIN sign-on for shared scanners will issue platform tokens on
  already-authenticated devices; it is a later addition, not covered here.
