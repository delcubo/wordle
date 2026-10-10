"""add tournaments.notify_admin (Telegram notifications about finished games)

Revision ID: g4c9e2b7d1f6
Revises: b5d2e8a3c6f1
Create Date: 2026-10-10 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'g4c9e2b7d1f6'
down_revision = 'b5d2e8a3c6f1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('notify_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'notify_admin', server_default=None)


def downgrade():
    op.drop_column('tournaments', 'notify_admin')
