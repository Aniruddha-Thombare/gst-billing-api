"""add_audit_log_immutability_trigger

Revision ID: a41799d951ca
Revises: 361d9618be0c
Create Date: 2026-05-08 19:02:14.644626

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a41799d951ca'
down_revision: Union[str, Sequence[str], None] = '361d9618be0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 
                'audit_logs is append-only. Updates and deletes are prohibited.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_logs_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_log_mutation();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_audit_log_mutation;"
    )
