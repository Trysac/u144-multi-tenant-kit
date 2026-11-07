"""Row-level multi-tenancy kit for PostgreSQL and Python.

Provides fail-closed row security policy generation, transaction-local tenant binding,
async-safe ContextVar tenant scoping, and validating WSGI middleware.

Threat Model:
    Defended:
        - Queries that omit tenant filters when connecting as non-owner, non-superuser roles.
        - HTTP requests without valid, authenticated, resolved tenants.
        - Context leakage across asyncio tasks and threads via ContextVars.
    Not Defended:
        - Superusers and roles with BYPASSRLS permissions.
        - Database connections that omit bind_tenant after BEGIN in pooled sessions.
        - Resolve functions that blindly trust client-supplied headers without authentication.
        - SQL injection elsewhere in the application.
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, Literal
from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment

__all__ = [
    "TenantError",
    "TenantErrorCode",
    "TenantMiddleware",
    "__version__",
    "bind_tenant",
    "current_tenant",
    "rls_policy_sql",
    "tenant_scope",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

TenantErrorCode = Literal["no_tenant", "tenant_switch", "invalid_tenant", "invalid_identifier"]

MAX_TENANT_ID_LENGTH: int = 64
MAX_IDENTIFIER_LENGTH: int = 63
MAX_SETTING_LENGTH: int = 128

_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SETTING_RE = re.compile(r"^[a-z_]+\.[a-z_]+$")

_CURRENT_TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)


class TenantError(Exception):
    """Base error class for multi-tenant kit operations."""

    def __init__(self, code: TenantErrorCode, message: str | None = None) -> None:
        self.code: TenantErrorCode = code
        msg = message or f"Tenant error: {code}"
        if len(msg) > 200:
            msg = msg[:197] + "..."
        super().__init__(msg)


def _validate_tenant_id(tenant_id: str) -> None:
    if (
        not isinstance(tenant_id, str)
        or len(tenant_id) > MAX_TENANT_ID_LENGTH
        or not _TENANT_ID_RE.match(tenant_id)
    ):
        raise TenantError("invalid_tenant", "Invalid tenant identifier format")


def _validate_identifier(identifier: str) -> None:
    if (
        not isinstance(identifier, str)
        or len(identifier) > MAX_IDENTIFIER_LENGTH
        or not _IDENTIFIER_RE.match(identifier)
    ):
        raise TenantError("invalid_identifier", "Invalid SQL identifier")


def _validate_setting(setting: str) -> None:
    if (
        not isinstance(setting, str)
        or len(setting) > MAX_SETTING_LENGTH
        or not _SETTING_RE.match(setting)
    ):
        raise TenantError("invalid_identifier", "Invalid configuration setting identifier")


def current_tenant() -> str:
    """Return the currently active tenant identifier.

    Raises:
        TenantError: with code 'no_tenant' if no tenant scope is active.
    """
    active = _CURRENT_TENANT.get()
    if active is None:
        raise TenantError("no_tenant", "No active tenant scope found")
    return active


class _TenantScopeContext(AbstractContextManager[None]):
    """Context manager governing active tenant ContextVar scope."""

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id
        self._tokens: list[contextvars.Token[str | None]] = []

    def __enter__(self) -> None:
        current = _CURRENT_TENANT.get()
        if current is not None and current != self._tenant_id:
            raise TenantError(
                "tenant_switch",
                "Switching tenants within an active scope is prohibited",
            )
        token = _CURRENT_TENANT.set(self._tenant_id)
        self._tokens.append(token)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._tokens:
            token = self._tokens.pop()
            _CURRENT_TENANT.reset(token)


def tenant_scope(tenant_id: str) -> AbstractContextManager[None]:
    """Context manager binding tenant_id for the duration of the enclosed block.

    Nested scopes with the same tenant ID are permitted. Attempting to nest a different
    tenant ID raises TenantError('tenant_switch') without altering the outer tenant.

    Raises:
        TenantError: with code 'invalid_tenant' if tenant_id format is invalid.
    """
    _validate_tenant_id(tenant_id)
    return _TenantScopeContext(tenant_id)


def rls_policy_sql(
    table: str,
    *,
    column: str = "tenant_id",
    setting: str = "app.tenant_id",
) -> str:
    """Generate PostgreSQL Row Level Security (RLS) SQL statements for a table.

    Returns ALTER TABLE ... ENABLE ROW LEVEL SECURITY, ALTER TABLE ... FORCE ROW LEVEL SECURITY,
    and CREATE POLICY statements configured to compare column with current_setting(setting, true).

    Raises:
        TenantError: with code 'invalid_identifier' if table, column, or setting is malformed.
    """
    _validate_identifier(table)
    _validate_identifier(column)
    _validate_setting(setting)

    policy_name = f"{table}_tenant_isolation"
    return (
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;\n'
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;\n'
        f'CREATE POLICY "{policy_name}" ON "{table}" '
        f'USING ("{column}" = current_setting(\x27{setting}\x27, true)) '
        f'WITH CHECK ("{column}" = current_setting(\x27{setting}\x27, true));'
    )


def bind_tenant(cursor: Any, *, setting: str = "app.tenant_id") -> None:
    """Bind the current tenant to a database transaction session via set_config.

    Executes SELECT set_config('app.tenant_id', %s, true) on the provided DB-API cursor.
    The setting is transaction-local (is_local=true), fail-closing if unset.

    Raises:
        TenantError: with code 'no_tenant' if called outside an active tenant scope,
            or code 'invalid_identifier' if setting is malformed.
    """
    _validate_setting(setting)
    tenant = current_tenant()
    cursor.execute(f"SELECT set_config('{setting}', %s, true)", (tenant,))


class _TenantScopeIterator:
    """Wraps an iterable WSGI response to maintain tenant context during iteration."""

    def __init__(self, tenant_id: str, iterable: Iterable[bytes]) -> None:
        self._tenant_id = tenant_id
        self._iterable = iterable
        self._iter: Iterator[bytes] = iter(iterable)

    def __iter__(self) -> _TenantScopeIterator:
        return self

    def __next__(self) -> bytes:
        with tenant_scope(self._tenant_id):
            return next(self._iter)

    def close(self) -> None:
        close_fn = getattr(self._iterable, "close", None)
        if callable(close_fn):
            with tenant_scope(self._tenant_id):
                close_fn()


class TenantMiddleware:
    """WSGI middleware resolving and enforcing tenant scope on incoming HTTP requests."""

    def __init__(
        self,
        app: WSGIApplication,
        *,
        resolve: Callable[[str], bool],
        header: str = "X-Tenant-ID",
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.app = app
        self.resolve = resolve
        self.header = header
        self.on_event = on_event
        normalized = header.upper().replace("-", "_")
        self._environ_key = normalized if normalized.startswith("HTTP_") else f"HTTP_{normalized}"

    def __call__(
        self,
        environ: WSGIEnvironment,
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        raw_header = environ.get(self._environ_key)
        if raw_header is None:
            if self.on_event is not None:
                self.on_event({"event": "tenant_rejected", "reason": "missing"})
            return self._error_response(start_response, "400 Bad Request", b"missing tenant")

        if not _TENANT_ID_RE.match(raw_header):
            if self.on_event is not None:
                self.on_event({"event": "tenant_rejected", "reason": "invalid"})
            return self._error_response(start_response, "400 Bad Request", b"invalid tenant")

        is_known = self.resolve(raw_header)
        if not is_known:
            if self.on_event is not None:
                self.on_event({"event": "tenant_rejected", "reason": "unknown"})
            return self._error_response(start_response, "403 Forbidden", b"unknown tenant")

        if self.on_event is not None:
            self.on_event({"event": "tenant_bound"})

        with tenant_scope(raw_header):
            result = self.app(environ, start_response)
            if isinstance(result, (list, tuple)):
                return result
            return _TenantScopeIterator(raw_header, result)

    def _error_response(
        self,
        start_response: StartResponse,
        status: str,
        body: bytes,
    ) -> list[bytes]:
        headers = [
            ("Content-Type", "text/plain"),
            ("Content-Length", str(len(body))),
        ]
        start_response(status, headers)
        return [body]
