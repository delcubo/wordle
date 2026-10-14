"""add tournaments.tie_resolutions (final order of tied places by tiebreak results)

Revision ID: i6e1a4d9f3b8
Revises: h5d0f3c8e2a7
Create Date: 2026-10-14 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'i6e1a4d9f3b8'
down_revision = 'h5d0f3c8e2a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('tie_resolutions', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('tournaments', 'tie_resolutions')
