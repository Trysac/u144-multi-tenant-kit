# Testing Strategy

Tests are located in `tests/test_multi_tenant_kit.py` and cover all exported functionality and acceptance criteria.

## Coverage Areas

- **Context Scoping & Nesting**: Validates `current_tenant()` behavior, permits same-tenant nesting, rejects cross-tenant nesting with `tenant_switch`, and ensures scope reset on exception.
- **Concurrency**: Verifies strict `ContextVar` isolation using `asyncio.gather` and `ThreadPoolExecutor`.
- **PostgreSQL DDL**: Verifies `rls_policy_sql` output structure and character-exactness.
- **Validation**: Ensures invalid identifiers (tables, tenants) correctly trigger `TenantError`.
- **Database Binding**: Uses a recording fake cursor to ensure `bind_tenant` executes the correct SQL with correct transaction-local settings.
- **WSGI Middleware**: Verifies status codes (400, 403) for missing/invalid/unknown tenants, and ensures the app executes inside the correct tenant scope.