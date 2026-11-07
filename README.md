# multi-tenant-kit

Row-level multi-tenancy helpers: contextvar tenant scope, exact Postgres RLS policy SQL, transaction-local tenant binding and a WSGI tenant middleware.

## The Problem

Multi-tenant SaaS applications often filter every query by `tenant_id` manually. One forgotten `WHERE` clause can cause catastrophic data leakage. While PostgreSQL Row-Level Security (RLS) can enforce isolation at the engine level, it requires precise wiring of the database policy, per-transaction session configuration, and the web request lifecycle.

## Installation

```bash
pip install trysac-multi-tenant-kit
```

## Usage Example

```python
from multi_tenant_kit import current_tenant, rls_policy_sql, tenant_scope

sql = rls_policy_sql("orders")
print(sql.splitlines()[0])

with tenant_scope("tenant-123"):
    active = current_tenant()
    print(f"Active tenant: {active}")
```

## API Summary

- `current_tenant() -> str`: Returns active tenant ID (raises `TenantError('no_tenant')` if unbound).
- `tenant_scope(tenant_id: str) -> AbstractContextManager[None]`: Context manager for `ContextVar` scoping. Raises `TenantError` on invalid formats or nested tenant switches.
- `rls_policy_sql(table: str, *, column: str = "tenant_id", setting: str = "app.tenant_id") -> str`: Generates strict RLS policy DDL.
- `bind_tenant(cursor: Any, *, setting: str = "app.tenant_id") -> None`: Executes `set_config(setting, tenant, true)` on a DB-API cursor.
- `TenantMiddleware(app, *, resolve: Callable[[str], bool], ...)`: WSGI middleware enforcing tenant resolution.
- `TenantError`: Exception with code `no_tenant`, `tenant_switch`, `invalid_tenant`, or `invalid_identifier`.

## Why not <best-known alternative>?

Unlike frameworks like `django-tenants` that impose specific ORM or schema architectures, this kit provides a lightweight, framework-agnostic set of primitives for implementing database-enforced row-level isolation in any standard Python/Postgres stack.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model and boundaries.