"""add marathon tournament type, tournaments.words_count and tournaments.end_date

Revision ID: l9b4d7f2e6c1
Revises: k8a3c6e1d5b9
Create Date: 2026-10-19 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'l9b4d7f2e6c1'
down_revision = 'k8a3c6e1d5b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('words_count', sa.Integer(), nullable=True))
    op.add_column('tournaments', sa.Column('end_date', sa.Date(), nullable=True))
    op.execute("ALTER TYPE tournamenttype ADD VALUE IF NOT EXISTS 'marathon'")


def downgrade():
    # Postgres не поддерживает удаление значения enum — откат схемы (не данных)
    # для новых значений типа не делаем, как и остальные подобные миграции.
    op.drop_column('tournaments', 'end_date')
    op.drop_column('tournaments', 'words_count')
