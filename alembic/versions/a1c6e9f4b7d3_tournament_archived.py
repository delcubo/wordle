"""add archived flag to tournaments

Revision ID: a1c6e9f4b7d3
Revises: f3b8d1e6a2c9
Create Date: 2026-09-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c6e9f4b7d3'
down_revision = 'f3b8d1e6a2c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'archived', server_default=None)


def downgrade():
    op.drop_column('tournaments', 'archived')
