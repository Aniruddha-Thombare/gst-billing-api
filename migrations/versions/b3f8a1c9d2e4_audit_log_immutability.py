"""audit_log_immutability

Revision ID: b3f8a1c9d2e4
Revises: 6c9886bdf023
Create Date: 2026-11-05 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3f8a1c9d2e4'
down_revision: Union[str, Sequence[str], None] = '6c9886bdf023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIONS_NEW = (
    "('create','update','delete','login','export','send','void','cancel',"
    "'logout','login_failed','activate','deactivate')"
)
_ACTIONS_OLD = "('create','update','delete','login','export')"
_ENTITIES_NEW = "('tenant','user','party','invoice','invoice_item','sequence','payment','refund')"
_ENTITIES_OLD = "('tenant','user','party','invoice','invoice_item','sequence','payment')"

_BLOCK_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_logs_block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' is not permitted',
        ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # The JSON GIN indexes are never queried and slow every audit insert.
    op.execute("DROP INDEX IF EXISTS idx_audit_logs_new_values_gin")
    op.execute("DROP INDEX IF EXISTS idx_audit_logs_old_values_gin")

    # Widen the allowed action / entity values.
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_audit_action")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_entity_type")
    op.create_check_constraint("check_audit_logs_audit_action", "audit_logs", f"action IN {_ACTIONS_NEW}")
    op.create_check_constraint("check_audit_logs_entity_type", "audit_logs", f"entity_type IN {_ENTITIES_NEW}")

    # Immutability: UPDATE, DELETE and TRUNCATE are rejected by the database itself.
    op.execute(_BLOCK_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_audit_logs_no_update_delete "
        "BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_block_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_logs_no_truncate "
        "BEFORE TRUNCATE ON audit_logs "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_block_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update_delete ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_block_mutation()")

    bind = op.get_bind()
    blocked = bind.execute(__import__("sqlalchemy").text(
        f"SELECT count(*) FROM audit_logs WHERE action NOT IN {_ACTIONS_OLD} "
        f"OR entity_type NOT IN {_ENTITIES_OLD}"
    )).scalar()
    if blocked:
        raise RuntimeError("Cannot downgrade: audit rows use values the old constraints reject.")

    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_audit_action")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_entity_type")
    op.create_check_constraint("check_audit_logs_audit_action", "audit_logs", f"action IN {_ACTIONS_OLD}")
    op.create_check_constraint("check_audit_logs_entity_type", "audit_logs", f"entity_type IN {_ENTITIES_OLD}")
    op.create_index("idx_audit_logs_new_values_gin", "audit_logs", ["new_values"], postgresql_using="gin")
    op.create_index("idx_audit_logs_old_values_gin", "audit_logs", ["old_values"], postgresql_using="gin")