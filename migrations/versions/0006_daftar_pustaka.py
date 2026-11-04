"""daftar pustaka

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('bib_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('authors', sa.Text(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('venue', sa.String(length=300), nullable=True),
    sa.Column('volume', sa.String(length=20), nullable=True),
    sa.Column('issue', sa.String(length=20), nullable=True),
    sa.Column('pages', sa.String(length=30), nullable=True),
    sa.Column('publisher', sa.String(length=200), nullable=True),
    sa.Column('doi', sa.String(length=200), nullable=True),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bib_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bib_entries_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('bib_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bib_entries_user_id'))
    op.drop_table('bib_entries')
