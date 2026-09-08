"""Durable recordings and Unicode FTS5 search."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recordings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.String(50), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("device", sa.String(120), nullable=False),
        sa.Column("audio_path", sa.Text()), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("raw_transcript", sa.Text()), sa.Column("edited_transcript", sa.Text()),
        sa.Column("result", sa.JSON()), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt", sa.Float(), nullable=False), sa.Column("error", sa.String(200)),
        sa.Column("markdown_path", sa.Text()), sa.Column("processing_mode", sa.String(32), nullable=False))
    op.create_index("ix_recordings_status", "recordings", ["status"])
    op.execute("CREATE VIRTUAL TABLE notes_fts USING fts5(id UNINDEXED, body, tokenize='unicode61')")


def downgrade():
    op.execute("DROP TABLE notes_fts")
    op.drop_table("recordings")
