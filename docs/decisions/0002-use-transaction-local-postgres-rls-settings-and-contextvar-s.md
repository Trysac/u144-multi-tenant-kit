# Use transaction-local Postgres RLS settings and ContextVar scopes for fail-closed multi-tenancy

Status: accepted (generated, pending human review)

## Context

Multi-tenant SaaS applications risk cross-tenant data leakage if application queries accidentally omit tenant WHERE filters. Application-level filtering is fragile and prone to human error. PostgreSQL Row Level Security (RLS) offers kernel-level query filtering, but requires coordinating transaction-local settings (set_config with is_local=true), fail-closed current_setting queries, and asynchronous context propagation.

## Decision

Implement tenant isolation using Python contextvars for async-safe scoping, generate strict Postgres RLS policies with FORCE ROW LEVEL SECURITY and NULL-safe current_setting defaults, enforce transaction-local tenant binding via bind_tenant, and intercept incoming HTTP requests via a validating WSGI middleware.

## Consequences

Developers gain robust, fail-closed multi-tenancy enforced at the database layer without manual WHERE clauses. Connection pooling requires calling bind_tenant on every transaction after BEGIN. Superusers and BYPASSRLS roles are explicitly not restricted by RLS.
