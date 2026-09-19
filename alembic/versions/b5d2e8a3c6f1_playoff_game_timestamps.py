"""add started_at/finished_at per side to playoff_games

Revision ID: b5d2e8a3c6f1
Revises: a8c1d4e7f2b6
Create Date: 2026-09-19 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'b5d2e8a3c6f1'
down_revision = 'a8c1d4e7f2b6'
branch_labels = None
depends_on = None


def upgrade():
    for col in ('entry_a_started_at', 'entry_a_finished_at', 'entry_b_started_at', 'entry_b_finished_at'):
        op.add_column('playoff_games', sa.Column(col, sa.DateTime(), nullable=True))


def downgrade():
    for col in ('entry_b_finished_at', 'entry_b_started_at', 'entry_a_finished_at', 'entry_a_started_at'):
        op.drop_column('playoff_games', col)
