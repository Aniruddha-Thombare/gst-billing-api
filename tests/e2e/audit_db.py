"""Direct DB access used ONLY to verify audit rows (the API has no audit read endpoint yet)."""

import uuid

import asyncpg


async def audit_table(db: asyncpg.Connection) -> str:
    rows = await db.fetch(
        """
        SELECT c.table_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND c.table_name ILIKE '%audit%'
        """
    )
    assert rows, "No table with 'audit' in its name and a tenant_id column found in gst_test"
    return rows[0]["table_name"]


async def count_audit_rows(db: asyncpg.Connection, tenant_id: str) -> int:
    table = await audit_table(db)
    return await db.fetchval(f'SELECT count(*) FROM "{table}" WHERE tenant_id = $1', uuid.UUID(tenant_id))
