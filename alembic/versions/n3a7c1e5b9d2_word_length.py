"""add tournaments.word_length and tournaments.word_plan (words of 5, 6 or 7 letters)

Revision ID: n3a7c1e5b9d2
Revises: m1c5e8a3f7d2
Create Date: 2026-10-21 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'n3a7c1e5b9d2'
down_revision = 'm1c5e8a3f7d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('word_length', sa.Integer(), nullable=False, server_default=sa.text('5')))
    op.alter_column('tournaments', 'word_length', server_default=None)
    op.add_column('tournaments', sa.Column('word_plan', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('tournaments', 'word_plan')
    op.drop_column('tournaments', 'word_length')
