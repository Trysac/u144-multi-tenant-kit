# Project Record

## Objective

To provide robust, fail-closed row-level multi-tenancy primitives for PostgreSQL and Python applications, preventing data leakage caused by missing `WHERE` clauses.

## Scope

- Async-safe, `ContextVar`-based tenant scoping.
- PostgreSQL Row-Level Security policy DDL generator.
- Transaction-local `set_config` binding for database connections.
- Validating WSGI tenant middleware.

## Out of Scope

- ASGI support.
- ORM-specific integrations (e.g., SQLAlchemy/Django models).
- Architecture alternatives like schema-per-tenant or database-per-tenant.
- Automated database migration runners.
- A live PostgreSQL instance in the test suite.

## Factory run u144 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4205 | 38456 | 0 | 0 | 0.0737 |
| fix-1 | gemini-3.8-flash | no | 37464 | 478 | 0 | 131632 | 0.0398 |
| fix-2 | gemini-3.8-flash | no | 28167 | 271 | 0 | 69031 | 0.0273 |
| fix-3 | gemini-3.8-flash | no | 14702 | 784 | 0 | 15742 | 0.0151 |
| audit | gemini-3.1-flash-lite | no | 36753 | 394 | 0 | 71279 | 0.0116 |
| docs | gemini-3.1-flash-lite | no | 188518 | 1293 | 0 | 0 | 0.0491 |

Total: $0.2165. Prices: Anthropic list prices.
