"""preset feedback dosen dan bank pertanyaan penguji

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('feedback_presets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dosen_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dosen_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('feedback_presets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_presets_dosen_id'), ['dosen_id'], unique=False)
    op.create_table('exam_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=12), nullable=True),
    sa.Column('major', sa.String(length=160), nullable=True),
    sa.Column('question', sa.String(length=400), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('exam_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_exam_questions_institution_id'), ['institution_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('exam_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exam_questions_institution_id'))
    op.drop_table('exam_questions')
    with op.batch_alter_table('feedback_presets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feedback_presets_dosen_id'))
    op.drop_table('feedback_presets')
