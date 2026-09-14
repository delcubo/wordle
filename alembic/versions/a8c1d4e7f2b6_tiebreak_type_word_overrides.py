"""add tournaments.word_overrides and tiebreak tournament type

Revision ID: a8c1d4e7f2b6
Revises: 54b339956dfa
Create Date: 2026-09-15 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8c1d4e7f2b6'
down_revision = '54b339956dfa'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('word_overrides', sa.JSON(), nullable=True))
    op.execute("ALTER TYPE tournamenttype ADD VALUE IF NOT EXISTS 'tiebreak'")


def downgrade():
    # Postgres не поддерживает удаление значения enum — откат схемы (не данных)
    # для новых значений типа не делаем, как и остальные подобные миграции.
    op.drop_column('tournaments', 'word_overrides')
