# Security Model

## Threat Model

### Defended
- **Data Leakage**: Queries that inadvertently omit tenant filters return zero rows (fail-closed) rather than data from other tenants, provided the connection is not a superuser.
- **Invalid Requests**: HTTP requests lacking a valid, resolved tenant are blocked by middleware with `400` or `403` status codes.
- **Context Leakage**: `ContextVars` prevent tenant identifier bleeding across concurrent `asyncio` tasks and OS threads.

### Not Defended
- **Superusers**: Roles with `BYPASSRLS` permission or superuser status bypass all RLS policies.
- **Session Mismanagement**: Database connections that fail to execute `bind_tenant` after `BEGIN` in a pooled session.
- **Blind Trust**: Middleware resolve functions that trust client-supplied headers without external authentication.
- **SQL Injection**: General SQL injection vulnerabilities outside the scope of the library's identifier sanitization.