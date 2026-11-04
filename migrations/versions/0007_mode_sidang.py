"""mode sidang

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sidang_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=12), nullable=False),
    sa.Column('persona', sa.String(length=12), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('max_questions', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sidang_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sidang_sessions_user_id'), ['user_id'], unique=False)
        batch_op.create_index('uq_sidang_active', ['user_id'], unique=True, sqlite_where=sa.text("status = 'aktif'"), postgresql_where=sa.text("status = 'aktif'"))
    op.create_table('sidang_turns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('idx', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sidang_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'idx')
    )
    with op.batch_alter_table('sidang_turns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sidang_turns_session_id'), ['session_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('sidang_turns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sidang_turns_session_id'))
    op.drop_table('sidang_turns')
    with op.batch_alter_table('sidang_sessions', schema=None) as batch_op:
        batch_op.drop_index('uq_sidang_active', sqlite_where=sa.text("status = 'aktif'"), postgresql_where=sa.text("status = 'aktif'"))
        batch_op.drop_index(batch_op.f('ix_sidang_sessions_user_id'))
    op.drop_table('sidang_sessions')
