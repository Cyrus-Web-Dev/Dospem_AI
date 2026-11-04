"""keamanan akun, persetujuan syarat, penghapusan akun, dan log akses dosen

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('pw_changed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('terms_accepted_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('terms_version', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_table('draft_accesses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dosen_id', sa.Integer(), nullable=False),
    sa.Column('mahasiswa_id', sa.Integer(), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('chapter_key', sa.String(length=40), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dosen_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mahasiswa_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('draft_accesses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_draft_accesses_dosen_id'), ['dosen_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_draft_accesses_mahasiswa_id'), ['mahasiswa_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('draft_accesses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_draft_accesses_mahasiswa_id'))
        batch_op.drop_index(batch_op.f('ix_draft_accesses_dosen_id'))
    op.drop_table('draft_accesses')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('terms_version')
        batch_op.drop_column('terms_accepted_at')
        batch_op.drop_column('pw_changed_at')
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_logins')
