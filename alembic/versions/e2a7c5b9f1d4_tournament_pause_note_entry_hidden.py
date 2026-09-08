"""tournament pause/note, entry hidden_from_standings, drop user.is_test

Revision ID: e2a7c5b9f1d4
Revises: d9f3b6a1c8e5
Create Date: 2026-09-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e2a7c5b9f1d4'
down_revision = 'd9f3b6a1c8e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('paused', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'paused', server_default=None)

    op.add_column('tournaments', sa.Column('note', sa.String(length=1000), nullable=True))

    op.add_column(
        'tournament_entries',
        sa.Column('hidden_from_standings', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('tournament_entries', 'hidden_from_standings', server_default=None)

    op.drop_column('users', 'is_test')


def downgrade():
    op.add_column('users', sa.Column('is_test', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_column('tournament_entries', 'hidden_from_standings')
    op.drop_column('tournaments', 'note')
    op.drop_column('tournaments', 'paused')
