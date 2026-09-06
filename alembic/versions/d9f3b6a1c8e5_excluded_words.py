"""add excluded_words table

Revision ID: d9f3b6a1c8e5
Revises: c4d8f2a9e7b1
Create Date: 2026-09-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd9f3b6a1c8e5'
down_revision = 'c4d8f2a9e7b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'excluded_words',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('word', sa.String(length=20), nullable=False),
        sa.Column('excluded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_excluded_words_word'), 'excluded_words', ['word'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_excluded_words_word'), table_name='excluded_words')
    op.drop_table('excluded_words')
