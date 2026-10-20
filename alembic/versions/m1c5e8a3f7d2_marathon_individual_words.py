"""marathon individual word sets: daily_words.entry_id, tournaments.individual_words

Revision ID: m1c5e8a3f7d2
Revises: l9b4d7f2e6c1
Create Date: 2026-10-20 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


revision = 'm1c5e8a3f7d2'
down_revision = 'l9b4d7f2e6c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tournaments', sa.Column('individual_words', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('tournaments', 'individual_words', server_default=None)
    op.add_column('daily_words', sa.Column('entry_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_daily_words_entry_id', 'daily_words', 'tournament_entries', ['entry_id'], ['id'])
    op.create_index('ix_daily_words_entry_id', 'daily_words', ['entry_id'])
    # общее слово уникально по (розыгрыш, номер), индивидуальное — по (розыгрыш, участник, номер)
    op.drop_constraint('uq_word_per_day', 'daily_words', type_='unique')
    op.create_index(
        'uq_word_per_day_shared', 'daily_words', ['tournament_id', 'day_number'], unique=True,
        postgresql_where=sa.text('entry_id IS NULL'),
    )
    op.create_index(
        'uq_word_per_day_entry', 'daily_words', ['tournament_id', 'entry_id', 'day_number'], unique=True,
        postgresql_where=sa.text('entry_id IS NOT NULL'),
    )


def downgrade():
    op.drop_index('uq_word_per_day_entry', table_name='daily_words')
    op.drop_index('uq_word_per_day_shared', table_name='daily_words')
    op.create_unique_constraint('uq_word_per_day', 'daily_words', ['tournament_id', 'day_number'])
    op.drop_index('ix_daily_words_entry_id', table_name='daily_words')
    op.drop_constraint('fk_daily_words_entry_id', 'daily_words', type_='foreignkey')
    op.drop_column('daily_words', 'entry_id')
    op.drop_column('tournaments', 'individual_words')
