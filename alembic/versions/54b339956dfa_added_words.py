"""add added_words table

Revision ID: 54b339956dfa
Revises: a1c6e9f4b7d3
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '54b339956dfa'
down_revision = 'a1c6e9f4b7d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'added_words',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('word', sa.String(length=20), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_added_words_word'), 'added_words', ['word'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_added_words_word'), table_name='added_words')
    op.drop_table('added_words')
