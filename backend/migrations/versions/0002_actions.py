"""Durable action journal and user preferences."""
from alembic import op
import sqlalchemy as sa
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('actions', sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('recording_id',sa.String(36),nullable=False),
        sa.Column('created_at',sa.String(50),nullable=False), sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(32),nullable=False), sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('error',sa.Text()))
    op.create_index('ix_actions_recording_id','actions',['recording_id'])
    op.create_table('preferences',sa.Column('key',sa.String(80),primary_key=True),sa.Column('value',sa.JSON(),nullable=False))


def downgrade():
    op.drop_table('actions')
    op.drop_table('preferences')
