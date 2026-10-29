"""bonus words: tournaments.bonus_enabled / bonus_every_days / bonus_default_length, daily_words.bonus_number

Revision ID: q6d0f4b8c3e5
Revises: p5c9e3a7b2d4
Create Date: 2026-10-29 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'q6d0f4b8c3e5'
down_revision = 'p5c9e3a7b2d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('bonus_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'bonus_enabled', server_default=None)
    op.add_column('tournaments', sa.Column('bonus_every_days', sa.Integer(), nullable=True))
    op.add_column('tournaments', sa.Column('bonus_default_length', sa.Integer(), nullable=False, server_default=sa.text('6')))
    op.alter_column('tournaments', 'bonus_default_length', server_default=None)
    op.add_column('daily_words', sa.Column('bonus_number', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('daily_words', 'bonus_number')
    op.drop_column('tournaments', 'bonus_default_length')
    op.drop_column('tournaments', 'bonus_every_days')
    op.drop_column('tournaments', 'bonus_enabled')
