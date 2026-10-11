"""hall of fame: hall_images, hall_entries, app_settings.hall_mode/hall_test_user_id

Revision ID: h5d0f3c8e2a7
Revises: g4c9e2b7d1f6
Create Date: 2026-10-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'h5d0f3c8e2a7'
down_revision = 'g4c9e2b7d1f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hall_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=40), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'hall_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('champion', sa.String(length=80), nullable=False),
        sa.Column('date_start', sa.Date(), nullable=False),
        sa.Column('date_end', sa.Date(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('table_image_id', sa.Integer(), nullable=True),
        sa.Column('bracket_image_id', sa.Integer(), nullable=True),
        sa.Column('certificate_image_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['table_image_id'], ['hall_images.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['bracket_image_id'], ['hall_images.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['certificate_image_id'], ['hall_images.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('app_settings', sa.Column('hall_mode', sa.String(length=10), nullable=False, server_default='off'))
    op.add_column('app_settings', sa.Column('hall_test_user_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_app_settings_hall_test_user', 'app_settings', 'users', ['hall_test_user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_app_settings_hall_test_user', 'app_settings', type_='foreignkey')
    op.drop_column('app_settings', 'hall_test_user_id')
    op.drop_column('app_settings', 'hall_mode')
    op.drop_table('hall_entries')
    op.drop_table('hall_images')
