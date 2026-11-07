# Architecture

`multi-tenant-kit` establishes row-level multi-tenant isolation across three application layers: the HTTP entrypoint, the asynchronous request context, and the database engine.

```
[ HTTP Request ] -> [ TenantMiddleware ]
                           |
                           v (validates & resolves)
                   [ tenant_scope ] (Python ContextVar)
                           |
                           v
                   [ bind_tenant ] (DB-API cursor)
                           |
                           v (SELECT set_config('app.tenant_id', %s, true))
            [ PostgreSQL Row Level Security Engine ]
```

## Design Decisions

### 1. Fail-Closed current_setting
In PostgreSQL, `current_setting(setting_name, true)` returns `NULL` when the setting has not been set in the current transaction. Because `"tenant_id" = NULL` evaluates to unknown/falsy, any query executed without tenant binding returns zero rows rather than leaking data.

### 2. Transaction Locality with is_local=true
Modern SaaS architectures rely on connection pools (e.g., PgBouncer, SQLAlchemy pool). If `set_config` were session-scoped, subsequent requests reusing the connection could inherit another tenant's identity. `bind_tenant` uses `is_local=true` (the third argument to `set_config`), which resets the setting immediately upon transaction `COMMIT` or `ROLLBACK`.

### 3. FORCE ROW LEVEL SECURITY
By default, PostgreSQL Row Level Security policies do not apply to the table owner. `rls_policy_sql` generates `ALTER TABLE ... FORCE ROW LEVEL SECURITY;` so that isolation holds even if migration scripts or application connections connect as the schema owner.

### 4. Asyncio and Thread Isolation via ContextVars
`tenant_scope` utilizes Python's standard `contextvars.ContextVar`. Tasks running concurrently under `asyncio.gather` or in OS thread pools retain separate context snapshots, preventing cross-tenant contamination.
