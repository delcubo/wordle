"""add tournaments.first_place (first place a tiebreak plays for, display shift)

Revision ID: j7f2b5e0a9c4
Revises: i6e1a4d9f3b8
Create Date: 2026-10-14 00:00:00.000002

"""
from alembic import op
import sqlalchemy as sa


revision = 'j7f2b5e0a9c4'
down_revision = 'i6e1a4d9f3b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('first_place', sa.Integer(), nullable=False, server_default='1'))
    op.alter_column('tournaments', 'first_place', server_default=None)


def downgrade():
    op.drop_column('tournaments', 'first_place')
