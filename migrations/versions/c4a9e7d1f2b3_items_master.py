"""items_master

Revision ID: c4a9e7d1f2b3
Revises: b3f8a1c9d2e4
Create Date: 2026-11-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4a9e7d1f2b3'
down_revision: Union[str, Sequence[str], None] = 'b3f8a1c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTITIES_NEW = "('tenant','user','party','invoice','invoice_item','sequence','payment','refund','catalog_item')"
_ENTITIES_PREV = "('tenant','user','party','invoice','invoice_item','sequence','payment','refund')"


def upgrade() -> None:
    op.create_table('items',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('hsn_sac_code', sa.String(length=8), nullable=True),
        sa.Column('unit', sa.String(length=10), server_default=sa.text("'PCS'"), nullable=False),
        sa.Column('rate', sa.Numeric(precision=17, scale=2), nullable=False),
        sa.Column('gst_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('cess_rate', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
        sa.Column('is_service', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('rate >= 0', name='check_items_rate_non_negative'),
        sa.CheckConstraint('gst_rate >= 0 AND gst_rate <= 100', name='check_items_gst_rate_range'),
        sa.CheckConstraint('cess_rate >= 0 AND cess_rate <= 100', name='check_items_cess_rate_range'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_items_tenant_name_lower', 'items', ['tenant_id', sa.text('lower(name)')], unique=True)
    op.create_index('idx_items_tenant_name_id', 'items', ['tenant_id', 'name', 'id'], unique=False)

    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_entity_type")
    op.create_check_constraint("check_audit_logs_entity_type", "audit_logs", f"entity_type IN {_ENTITIES_NEW}")


def downgrade() -> None:
    bind = op.get_bind()
    blocked = bind.execute(sa.text("SELECT count(*) FROM audit_logs WHERE entity_type = 'catalog_item'")).scalar()
    if blocked:
        raise RuntimeError("Cannot downgrade: audit rows reference catalog_item.")
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS check_audit_logs_entity_type")
    op.create_check_constraint("check_audit_logs_entity_type", "audit_logs", f"entity_type IN {_ENTITIES_PREV}")
    op.drop_index('idx_items_tenant_name_id', table_name='items')
    op.drop_index('uq_items_tenant_name_lower', table_name='items')
    op.drop_table('items')