"""INTEGRATION test (direct DB): the audit table is append-only and mutations write rows."""

import uuid

import asyncpg
import pytest

from tests.e2e.audit_db import audit_table, count_audit_rows
from tests.e2e.helpers import PASSWORD, create_party, login, register_tenant


async def _expect_integrity_violation(db: asyncpg.Connection, statement: str, *args: object) -> None:
    with pytest.raises(asyncpg.PostgresError) as caught:
        async with db.transaction():
            await db.execute(statement, *args)
    assert str(caught.value.sqlstate).startswith("23"), (
        f"expected SQLSTATE class 23 (integrity violation), got {caught.value.sqlstate}: {caught.value}"
    )


async def test_audit_rows_cannot_be_updated_deleted_or_truncated(client, db):
    owner = await register_tenant(client)
    await create_party(client, owner)
    table = await audit_table(db)
    tenant = uuid.UUID(owner.tenant_id)
    assert await count_audit_rows(db, owner.tenant_id) >= 1

    await _expect_integrity_violation(db, f'UPDATE "{table}" SET tenant_id = tenant_id WHERE tenant_id = $1', tenant)
    await _expect_integrity_violation(db, f'DELETE FROM "{table}" WHERE tenant_id = $1', tenant)
    await _expect_integrity_violation(db, f'TRUNCATE TABLE "{table}"')
    assert await count_audit_rows(db, owner.tenant_id) >= 1


async def test_party_create_writes_exactly_one_audit_row(client, db):
    owner = await register_tenant(client)
    before = await count_audit_rows(db, owner.tenant_id)
    await create_party(client, owner)
    assert await count_audit_rows(db, owner.tenant_id) == before + 1


async def test_failed_login_is_audited(client, db):
    owner = await register_tenant(client)
    before = await count_audit_rows(db, owner.tenant_id)
    response = await login(client, owner.email, "Wrong!Passw0rd#9")
    assert response.status_code == 401
    assert await count_audit_rows(db, owner.tenant_id) == before + 1


async def test_failed_mutation_writes_no_audit_row(client, db):
    owner = await register_tenant(client)
    before = await count_audit_rows(db, owner.tenant_id)
    bad_party = {"name": "", "party_type": "customer"}
    response = await client.post("/api/v1/parties", headers=owner.auth, json=bad_party)
    assert response.status_code == 422
    assert await count_audit_rows(db, owner.tenant_id) == before
