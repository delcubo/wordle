"""add app_settings table

Revision ID: b7e4a1f6c3d2
Revises: a3f1c9d8e2b4
Create Date: 2026-09-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e4a1f6c3d2'
down_revision = 'a3f1c9d8e2b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('theme', sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('app_settings')
