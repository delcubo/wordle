"""team tiebreak: tiebreak_participants.daily_word_id / team_id (personal word and team of a round participant)

Revision ID: p5c9e3a7b2d4
Revises: o4b8d2f6a1c3
Create Date: 2026-10-24 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'p5c9e3a7b2d4'
down_revision = 'o4b8d2f6a1c3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tiebreak_participants', sa.Column('daily_word_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tiebreak_participants_daily_word_id', 'tiebreak_participants', 'daily_words', ['daily_word_id'], ['id'])
    op.add_column('tiebreak_participants', sa.Column('team_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tiebreak_participants_team_id', 'tiebreak_participants', 'teams', ['team_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_tiebreak_participants_team_id', 'tiebreak_participants', type_='foreignkey')
    op.drop_column('tiebreak_participants', 'team_id')
    op.drop_constraint('fk_tiebreak_participants_daily_word_id', 'tiebreak_participants', type_='foreignkey')
    op.drop_column('tiebreak_participants', 'daily_word_id')
