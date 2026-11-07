"""Unit tests for multi_tenant_kit exercising every exported function and acceptance item."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Iterator
from typing import Any

import pytest

from multi_tenant_kit import (
    TenantError,
    TenantMiddleware,
    bind_tenant,
    current_tenant,
    rls_policy_sql,
    tenant_scope,
)


class FakeCursor:
    """Recording DB-API fake cursor."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))


class ResponseRecorder:
    """WSGI start_response callback recorder."""

    def __init__(self) -> None:
        self.status: str | None = None
        self.headers: list[tuple[str, str]] = []

    def __call__(
        self,
        status: str,
        headers: list[tuple[str, str]],
        exc_info: Any = None,
    ) -> None:
        self.status = status
        self.headers = headers


def test_acceptance_1_tenant_scope_and_switching() -> None:
    """Inside with tenant_scope('acme'): current_tenant() == 'acme'; outside any scope
    current_tenant() raises TenantError with code 'no_tenant'; a nested tenant_scope('other')
    raises code 'tenant_switch' and the outer tenant stays 'acme'.
    """
    with pytest.raises(TenantError) as exc_outside:
        current_tenant()
    assert exc_outside.value.code == "no_tenant"

    with tenant_scope("acme"):
        assert current_tenant() == "acme"
        with pytest.raises(TenantError) as exc_switch, tenant_scope("other"):
            pass
        assert exc_switch.value.code == "tenant_switch"
        assert current_tenant() == "acme"

    with pytest.raises(TenantError) as exc_after:
        current_tenant()
    assert exc_after.value.code == "no_tenant"


def test_acceptance_2_concurrent_asyncio_tasks_and_exception_reset() -> None:
    """Two asyncio tasks running tenant_scope('a') and tenant_scope('b') concurrently
    each observe only their own tenant, and the scope is reset after an exception inside it.
    """
    results: dict[str, list[str]] = {"a": [], "b": []}

    async def task_a() -> None:
        with tenant_scope("a"):
            results["a"].append(current_tenant())
            await asyncio.sleep(0.005)
            results["a"].append(current_tenant())

    async def task_b() -> None:
        with tenant_scope("b"):
            results["b"].append(current_tenant())
            await asyncio.sleep(0.005)
            results["b"].append(current_tenant())

    async def runner() -> None:
        await asyncio.gather(task_a(), task_b())

    asyncio.run(runner())
    assert results["a"] == ["a", "a"]
    assert results["b"] == ["b", "b"]

    with pytest.raises(RuntimeError, match="boom"), tenant_scope("a"):
        assert current_tenant() == "a"
        raise RuntimeError("boom")

    with pytest.raises(TenantError) as exc_reset:
        current_tenant()
    assert exc_reset.value.code == "no_tenant"


def test_acceptance_3_rls_policy_sql_verbatim() -> None:
    """rls_policy_sql('orders') returns exactly expected DDL and policy SQL."""
    expected = (
        'ALTER TABLE "orders" ENABLE ROW LEVEL SECURITY;\n'
        'ALTER TABLE "orders" FORCE ROW LEVEL SECURITY;\n'
        'CREATE POLICY "orders_tenant_isolation" ON "orders" '
        "USING (\"tenant_id\" = current_setting('app.tenant_id', true)) "
        "WITH CHECK (\"tenant_id\" = current_setting('app.tenant_id', true));"
    )
    actual = rls_policy_sql("orders")
    assert actual == expected


def test_acceptance_4_validation_invalid_identifier_and_tenant() -> None:
    """rls_policy_sql('orders; drop') and tenant ids 'a b' or a 65-character id
    raise TenantError with codes 'invalid_identifier' and 'invalid_tenant'.
    """
    with pytest.raises(TenantError) as exc_id:
        rls_policy_sql("orders; drop")
    assert exc_id.value.code == "invalid_identifier"

    with pytest.raises(TenantError) as exc_t1:
        tenant_scope("a b")
    assert exc_t1.value.code == "invalid_tenant"

    long_id = "a" * 65
    with pytest.raises(TenantError) as exc_t2:
        tenant_scope(long_id)
    assert exc_t2.value.code == "invalid_tenant"


def test_acceptance_5_bind_tenant_execution_and_fail_closed() -> None:
    """bind_tenant(cursor) inside tenant_scope('acme') executes exactly
    SELECT set_config('app.tenant_id', %s, true) with params ('acme',) on a recording fake cursor,
    and outside a scope raises code 'no_tenant' without executing anything.
    """
    cursor = FakeCursor()
    with pytest.raises(TenantError) as exc_unbound:
        bind_tenant(cursor)
    assert exc_unbound.value.code == "no_tenant"
    assert len(cursor.calls) == 0

    with tenant_scope("acme"):
        bind_tenant(cursor)

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert sql == "SELECT set_config('app.tenant_id', %s, true)"
    assert params == ("acme",)


def test_acceptance_6_tenant_middleware_responses() -> None:
    """TenantMiddleware(app, resolve=lambda t: t == 'acme') returns '400 Bad Request'
    with body b'missing tenant' when the 'X-Tenant-ID' header is absent, '400 Bad Request'
    with b'invalid tenant' for 'a b', '403 Forbidden' with b'unknown tenant' for 'zzz',
    and calls app inside tenant_scope('acme') for 'acme'.
    """

    def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        tenant = current_tenant()
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [f"ok: {tenant}".encode()]

    middleware = TenantMiddleware(app, resolve=lambda t: t == "acme")

    # 1. Header absent
    rec_missing = ResponseRecorder()
    body_missing = b"".join(middleware({}, rec_missing))
    assert rec_missing.status == "400 Bad Request"
    assert body_missing == b"missing tenant"

    # 2. Invalid format ('a b')
    rec_invalid = ResponseRecorder()
    body_invalid = b"".join(middleware({"HTTP_X_TENANT_ID": "a b"}, rec_invalid))
    assert rec_invalid.status == "400 Bad Request"
    assert body_invalid == b"invalid tenant"

    # 3. Unknown tenant ('zzz')
    rec_unknown = ResponseRecorder()
    body_unknown = b"".join(middleware({"HTTP_X_TENANT_ID": "zzz"}, rec_unknown))
    assert rec_unknown.status == "403 Forbidden"
    assert body_unknown == b"unknown tenant"

    # 4. Valid known tenant ('acme')
    rec_ok = ResponseRecorder()
    body_ok = b"".join(middleware({"HTTP_X_TENANT_ID": "acme"}, rec_ok))
    assert rec_ok.status == "200 OK"
    assert body_ok == b"ok: acme"


def test_acceptance_7_on_event_payloads_and_sentinel_suppression() -> None:
    """on_event receives {'event': 'tenant_rejected', 'reason': 'unknown'} for 'zzz'
    and {'event': 'tenant_bound'} for 'acme', and no payload contains the header value 'SENTINEL-7f3a'.
    """
    events: list[dict[str, Any]] = []

    def dummy_app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        start_response("200 OK", [])
        return [b"ok"]

    middleware = TenantMiddleware(
        dummy_app,
        resolve=lambda t: t in ("acme", "SENTINEL-7f3a"),
        on_event=events.append,
    )

    # 1. Test for 'zzz'
    rec_zzz = ResponseRecorder()
    middleware({"HTTP_X_TENANT_ID": "zzz"}, rec_zzz)
    assert {"event": "tenant_rejected", "reason": "unknown"} in events

    # 2. Test for 'acme'
    rec_acme = ResponseRecorder()
    middleware({"HTTP_X_TENANT_ID": "acme"}, rec_acme)
    assert {"event": "tenant_bound"} in events

    # 3. Test with sentinel header value
    sentinel = "SENTINEL-7f3a"
    rec_sentinel = ResponseRecorder()
    res = middleware({"HTTP_X_TENANT_ID": sentinel}, rec_sentinel)
    body_sentinel = b"".join(res)

    assert sentinel.encode() not in body_sentinel
    for event in events:
        for k, v in event.items():
            assert sentinel not in str(k)
            assert sentinel not in str(v)


def test_nested_same_tenant_scope_allowed() -> None:
    """Nested scopes with the exact same tenant ID are allowed and exit cleanly."""
    with tenant_scope("acme"):
        assert current_tenant() == "acme"
        with tenant_scope("acme"):
            assert current_tenant() == "acme"
        assert current_tenant() == "acme"

    with pytest.raises(TenantError) as exc:
        current_tenant()
    assert exc.value.code == "no_tenant"


def test_reused_context_manager_instance() -> None:
    """A context manager instance can be re-entered sequentially."""
    scope = tenant_scope("tenant_reuse")
    with scope:
        assert current_tenant() == "tenant_reuse"
    with pytest.raises(TenantError):
        current_tenant()
    with scope:
        assert current_tenant() == "tenant_reuse"


def test_thread_isolation() -> None:
    """ContextVars maintain independent tenant context across concurrent OS threads."""

    def worker(tenant: str) -> bool:
        with tenant_scope(tenant):
            return current_tenant() == tenant

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(worker, "thread_1")
        f2 = executor.submit(worker, "thread_2")
        assert f1.result() is True
        assert f2.result() is True


def test_rls_policy_sql_custom_params_and_validation() -> None:
    """Test parameterization of column and setting, plus identifier validation."""
    sql = rls_policy_sql("invoices", column="org_id", setting="corp.org_id")
    assert 'ALTER TABLE "invoices" ENABLE ROW LEVEL SECURITY;' in sql
    assert 'ALTER TABLE "invoices" FORCE ROW LEVEL SECURITY;' in sql
    assert 'CREATE POLICY "invoices_tenant_isolation" ON "invoices"' in sql
    assert "USING (\"org_id\" = current_setting('corp.org_id', true))" in sql
    assert "WITH CHECK (\"org_id\" = current_setting('corp.org_id', true));" in sql

    # Invalid column
    with pytest.raises(TenantError) as exc_col:
        rls_policy_sql("invoices", column="invalid-col")
    assert exc_col.value.code == "invalid_identifier"

    # Invalid setting
    with pytest.raises(TenantError) as exc_setting:
        rls_policy_sql("invoices", setting="not_a_dot_setting")
    assert exc_setting.value.code == "invalid_identifier"

    # Non-string identifier
    with pytest.raises(TenantError) as exc_type:
        rls_policy_sql(123)  # type: ignore[arg-type]
    assert exc_type.value.code == "invalid_identifier"


def test_bind_tenant_custom_setting_and_invalid_setting() -> None:
    """Test bind_tenant with custom setting and malformed setting validation."""
    cursor = FakeCursor()
    with tenant_scope("tenant_custom"):
        bind_tenant(cursor, setting="custom.tenant_id")
        assert cursor.calls[0] == (
            "SELECT set_config('custom.tenant_id', %s, true)",
            ("tenant_custom",),
        )

        with pytest.raises(TenantError) as exc:
            bind_tenant(cursor, setting="invalid;setting")
        assert exc.value.code == "invalid_identifier"


def test_middleware_event_reasons_and_exception_propagation() -> None:
    """Verify all rejected reasons in on_event, custom headers, and exception bubbling."""
    recorded_events: list[dict[str, Any]] = []

    def failing_resolve(t: str) -> bool:
        raise ConnectionError("Auth service timeout")

    middleware = TenantMiddleware(
        lambda env, sr: [b"ok"],
        resolve=failing_resolve,
        header="HTTP_CUSTOM_TENANT",
        on_event=recorded_events.append,
    )

    # Missing
    rec_missing = ResponseRecorder()
    middleware({}, rec_missing)
    assert {"event": "tenant_rejected", "reason": "missing"} in recorded_events

    # Invalid
    rec_invalid = ResponseRecorder()
    middleware({"HTTP_CUSTOM_TENANT": "bad/id"}, rec_invalid)
    assert {"event": "tenant_rejected", "reason": "invalid"} in recorded_events

    # Resolve error propagates
    rec_err = ResponseRecorder()
    with pytest.raises(ConnectionError, match="Auth service timeout"):
        middleware({"HTTP_CUSTOM_TENANT": "valid_id"}, rec_err)


def test_middleware_streaming_response_maintains_scope() -> None:
    """Verify that iterable generator responses evaluate each chunk inside tenant scope."""

    def streaming_app(environ: dict[str, Any], start_response: Any) -> Iterator[bytes]:
        start_response("200 OK", [("Content-Type", "text/plain")])

        def generate() -> Iterator[bytes]:
            yield f"chunk1:{current_tenant()},".encode()
            yield f"chunk2:{current_tenant()}".encode()

        return generate()

    middleware = TenantMiddleware(streaming_app, resolve=lambda t: t == "stream_tenant")
    rec = ResponseRecorder()
    response_iter = middleware({"HTTP_X_TENANT_ID": "stream_tenant"}, rec)
    chunks = list(response_iter)
    assert b"".join(chunks) == b"chunk1:stream_tenant,chunk2:stream_tenant"


def test_middleware_streaming_close_called_inside_scope() -> None:
    """Verify that response .close() is invoked inside tenant scope."""
    closed_tenant: list[str] = []

    class ClosableIterator:
        def __iter__(self) -> Iterator[bytes]:
            yield b"data"

        def close(self) -> None:
            closed_tenant.append(current_tenant())

    def closable_app(environ: dict[str, Any], start_response: Any) -> ClosableIterator:
        start_response("200 OK", [])
        return ClosableIterator()

    middleware = TenantMiddleware(closable_app, resolve=lambda t: t == "close_tenant")
    rec = ResponseRecorder()
    res = middleware({"HTTP_X_TENANT_ID": "close_tenant"}, rec)
    if hasattr(res, "close"):
        res.close()
    assert closed_tenant == ["close_tenant"]


def test_tenant_error_message_truncation() -> None:
    """TenantError truncates overly verbose error messages to <= 200 characters."""
    long_msg = "x" * 300
    err = TenantError("invalid_tenant", long_msg)
    assert len(str(err)) <= 200
    assert str(err).endswith("...")
    assert err.code == "invalid_tenant"


def test_adversarial_identifier_and_tenant_inputs() -> None:
    """Adversarial neighbours: null bytes, newlines, semicolons, casing, lengths."""
    adversarial_tenants = [
        "",
        "a b",
        "tenant\x00null",
        "tenant\ninjection",
        "tenant;drop",
        "a" * 65,
        "tenant/slash",
        "tenant\\backslash",
        "tenant@domain",
    ]
    for bad in adversarial_tenants:
        with pytest.raises(TenantError) as exc:
            tenant_scope(bad)
        assert exc.value.code == "invalid_tenant"

    adversarial_identifiers = [
        "",
        "Orders",  # uppercase not allowed
        "1orders",  # starts with digit
        "orders; drop",
        'orders"',
        "orders--",
        "a" * 64,  # max identifier length is 63
    ]
    for bad_id in adversarial_identifiers:
        with pytest.raises(TenantError) as exc_id:
            rls_policy_sql(bad_id)
        assert exc_id.value.code == "invalid_identifier"
