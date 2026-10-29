"""playoff: playoff_matches.games_required (mandatory games per match)

Revision ID: r7e1a5c9d4f6
Revises: q6d0f4b8c3e5
Create Date: 2026-10-30 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'r7e1a5c9d4f6'
down_revision = 'q6d0f4b8c3e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('playoff_matches', sa.Column('games_required', sa.Integer(), nullable=False, server_default=sa.text('1')))
    op.alter_column('playoff_matches', 'games_required', server_default=None)


def downgrade():
    op.drop_column('playoff_matches', 'games_required')
