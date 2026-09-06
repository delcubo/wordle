"""add active/archived flags for entries and users

Revision ID: a3f1c9d8e2b4
Revises: 7fb25ebbd4f5
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3f1c9d8e2b4'
down_revision = '7fb25ebbd4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tournament_entries',
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column('tournament_entries', 'active', server_default=None)

    op.add_column(
        'users',
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'archived', server_default=None)

    op.add_column(
        'users',
        sa.Column('is_test', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'is_test', server_default=None)


def downgrade():
    op.drop_column('users', 'is_test')
    op.drop_column('users', 'archived')
    op.drop_column('tournament_entries', 'active')
