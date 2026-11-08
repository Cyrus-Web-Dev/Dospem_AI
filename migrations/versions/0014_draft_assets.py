"""gambar per bab (hasil unggah .docx)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'draft_assets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner', sa.String(length=64), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('chapter_key', sa.String(length=40), nullable=False),
        sa.Column('sha', sa.String(length=16), nullable=False),
        sa.Column('mime', sa.String(length=20), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('alt', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('owner', 'doc_type', 'chapter_key', 'sha'),
    )
    op.create_index(op.f('ix_draft_assets_owner'), 'draft_assets', ['owner'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_draft_assets_owner'), table_name='draft_assets')
    op.drop_table('draft_assets')
