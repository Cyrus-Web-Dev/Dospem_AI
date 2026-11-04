"""catatan dosen, riwayat revisi, dan jejak baca dosen

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('supervisor_notes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('supervision_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=True),
    sa.Column('chapter_key', sa.String(length=40), nullable=True),
    sa.Column('session_date', sa.Date(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['supervision_id'], ['supervisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('supervisor_notes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_supervisor_notes_supervision_id'), ['supervision_id'], unique=False)
    op.create_table('draft_revisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('draft_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('words', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('draft_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_draft_revisions_draft_id'), ['draft_id'], unique=False)
    op.create_table('dosen_views',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dosen_id', sa.Integer(), nullable=False),
    sa.Column('mahasiswa_id', sa.Integer(), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('chapter_key', sa.String(length=40), nullable=False),
    sa.Column('revision_id', sa.Integer(), nullable=True),
    sa.Column('seen_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dosen_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mahasiswa_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['draft_revisions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dosen_id', 'mahasiswa_id', 'doc_type', 'chapter_key')
    )
    with op.batch_alter_table('dosen_views', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dosen_views_dosen_id'), ['dosen_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('dosen_views', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dosen_views_dosen_id'))
    op.drop_table('dosen_views')
    with op.batch_alter_table('draft_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_draft_revisions_draft_id'))
    op.drop_table('draft_revisions')
    with op.batch_alter_table('supervisor_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supervisor_notes_supervision_id'))
    op.drop_table('supervisor_notes')
