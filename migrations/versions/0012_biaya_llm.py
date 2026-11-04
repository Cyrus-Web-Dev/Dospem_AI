"""cache hasil LLM dan agregat pemakaian token

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('llm_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner', sa.String(length=64), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner', 'key')
    )
    with op.batch_alter_table('llm_cache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_cache_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_llm_cache_owner'), ['owner'], unique=False)
    op.create_table('llm_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('institution_id', sa.Integer(), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('cache_hits', sa.Integer(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('day', 'kind', 'institution_id')
    )
    with op.batch_alter_table('llm_usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_usage_day'), ['day'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('llm_usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_usage_day'))
    op.drop_table('llm_usage')
    with op.batch_alter_table('llm_cache', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_cache_owner'))
        batch_op.drop_index(batch_op.f('ix_llm_cache_created_at'))
    op.drop_table('llm_cache')
