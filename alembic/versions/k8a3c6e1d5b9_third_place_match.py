"""add tournaments.third_place_match and playoff_matches.is_third_place

Revision ID: k8a3c6e1d5b9
Revises: j7f2b5e0a9c4
Create Date: 2026-10-17 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'k8a3c6e1d5b9'
down_revision = 'j7f2b5e0a9c4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('third_place_match', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'third_place_match', server_default=None)
    op.add_column('playoff_matches', sa.Column('is_third_place', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('playoff_matches', 'is_third_place', server_default=None)


def downgrade():
    op.drop_column('playoff_matches', 'is_third_place')
    op.drop_column('tournaments', 'third_place_match')
