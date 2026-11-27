# ADR 0004: Tenant users, built-in roles and permission checks

- Status: accepted
- Date: 2026-11-26

## Decision

The identity provider says who someone is and which tenants they may enter
(ADR 0003). What they may do inside a tenant is platform data, managed by that
tenant's admins.

- **Users are per tenant.** `kernel.users` is tenant-scoped with forced RLS,
  keyed by `(tenant_id, issuer, subject)`. Someone in two tenants has a row in
  each, with separate roles and status. No table spans tenants.
- **Provisioned on first sign-in, with no roles.** The first request in a tenant
  creates the user's row; access is then granted by an admin, never assumed.
  Provisioning runs in its own short transaction, so a refused first request
  still leaves the user visible to admins. The row is refreshed only when the
  profile changes or every 15 minutes, so most requests don't write.
- **Built-in roles, global and read-only.** `kernel.roles` holds `admin`,
  `operator` and `viewer`, each a list of permission strings. The app role can
  read it but not change it, so no tenant can grant itself new permissions.
  Custom per-tenant roles can be added later as tenant-scoped rows.
- **Assignments are per tenant.** `kernel.user_roles` is tenant-scoped with
  forced RLS. Its primary key and its foreign key to users both include
  `tenant_id`: an assignment can only point at a user in the same tenant, and a
  constraint error can't reveal another tenant's rows.
- **Routes declare permissions.** `Depends(require(Permission.X))` returns the
  caller's `Access` or answers 403. Permissions are a `StrEnum` in code; a test
  checks the role catalogue uses only known permissions.
- **Users are disabled, never deleted** (the app role has no DELETE on users), so
  audit history keeps its actors. A disabled user gets 403 in that tenant.
- **A tenant keeps an active admin.** Changing roles or status takes a
  per-tenant advisory lock, then checks an active admin remains; otherwise the
  change is rolled back with 409. Admins can't disable themselves.
- **Dev users** in the Keycloak realm have fixed ids, so `just seed` can grant
  their roles before they first sign in.

## Considered

- Roles from identity-provider groups: one place to manage access, but ties
  warehouse permissions to each customer's directory and to provider-specific
  setup, and can't be scoped per tenant for people in several.
- A global users table with tenant memberships: one row per person, but the
  app role would need to read users across tenants, breaking the rule that
  every tenant-scoped read goes through RLS.
- Granting a default role (viewer) on first sign-in: friendlier, but anyone the
  provider puts in a tenant group would see data before an admin decides.

## Consequences

- A new user can do nothing until an admin grants a role; the users list shows
  them waiting.
- Permission checks read the user's roles on every request (one indexed query
  in the same short transaction as provisioning).
- Audit (next M1 step) records `Access.user_id` as the actor.
