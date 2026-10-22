"""marathon teams: teams table, tournament_entries.team_id, tournaments.teams_enabled / team_tie_resolutions

Revision ID: o4b8d2f6a1c3
Revises: n3a7c1e5b9d2
Create Date: 2026-10-23 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'o4b8d2f6a1c3'
down_revision = 'n3a7c1e5b9d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tournament_id', sa.Integer(), sa.ForeignKey('tournaments.id'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tournament_id', 'name', name='uq_team_name_per_tournament'),
    )
    op.create_index('ix_teams_tournament_id', 'teams', ['tournament_id'])
    op.add_column('tournaments', sa.Column('teams_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'teams_enabled', server_default=None)
    op.add_column('tournaments', sa.Column('team_tie_resolutions', sa.JSON(), nullable=True))
    op.add_column('tournament_entries', sa.Column('team_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_entries_team_id', 'tournament_entries', 'teams', ['team_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_entries_team_id', 'tournament_entries', type_='foreignkey')
    op.drop_column('tournament_entries', 'team_id')
    op.drop_column('tournaments', 'team_tie_resolutions')
    op.drop_column('tournaments', 'teams_enabled')
    op.drop_index('ix_teams_tournament_id', table_name='teams')
    op.drop_table('teams')
