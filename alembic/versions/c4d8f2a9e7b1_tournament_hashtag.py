"""add hashtag to tournaments

Revision ID: c4d8f2a9e7b1
Revises: b7e4a1f6c3d2
Create Date: 2026-09-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d8f2a9e7b1'
down_revision = 'b7e4a1f6c3d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('hashtag', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('tournaments', 'hashtag')
