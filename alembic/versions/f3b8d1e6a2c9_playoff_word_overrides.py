"""add word_overrides to playoff_matches

Revision ID: f3b8d1e6a2c9
Revises: e2a7c5b9f1d4
Create Date: 2026-09-09 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3b8d1e6a2c9'
down_revision = 'e2a7c5b9f1d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('playoff_matches', sa.Column('word_overrides', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('playoff_matches', 'word_overrides')
