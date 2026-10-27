"""Initial four-table registry

Revision ID: e49ff864f16a
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "e49ff864f16a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("official_domain", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="employer_name"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employer_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("board_identifier", sa.String(), nullable=False),
        sa.Column("careers_url", sa.String(), nullable=False),
        sa.Column("api_endpoint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="candidate", nullable=False),
        sa.Column(
            "validated_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "last_success_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "poll_interval_minutes", sa.Integer(), server_default="60", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("provider = 'greenhouse'", name="supported_provider"),
        sa.CheckConstraint(
            "status != 'validated' OR validated_at IS NOT NULL",
            name="source_validation_time",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'validated', 'paused', 'error')",
            name="source_status",
        ),
        sa.CheckConstraint("consecutive_failures >= 0", name="source_failures"),
        sa.CheckConstraint("length(trim(board_identifier)) > 0", name="source_board"),
        sa.CheckConstraint("poll_interval_minutes > 0", name="source_interval"),
        sa.ForeignKeyConstraint(
            ["employer_id"],
            ["employers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "board_identifier", name="uq_source_board"),
    )
    op.create_table(
        "poll_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("post_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'complete_success', 'partial', 'failed')",
            name="poll_status",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="poll_time_order"
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="poll_http"
        ),
        sa.CheckConstraint("post_count IS NULL OR post_count >= 0", name="poll_count"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["job_sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "postings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_posting_id", sa.String(), nullable=False),
        sa.Column("external_requisition_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("canonical_job_url", sa.String(), nullable=False),
        sa.Column("apply_url", sa.String(), nullable=False),
        sa.Column("description_text", sa.String(), nullable=False),
        sa.Column(
            "source_published_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column(
            "source_updated_at",
            sa.DateTime(),
            nullable=True,
        ),
        sa.Column("date_provenance", sa.String(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="unknown", nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'missing_pending', 'closed', 'unknown')",
            name="posting_status",
        ),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name="posting_seen_order"),
        sa.CheckConstraint(
            "length(trim(external_posting_id)) > 0", name="posting_identity"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["job_sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "external_posting_id", name="uq_posting_identity"
        ),
    )


def downgrade() -> None:
    op.drop_table("postings")
    op.drop_table("poll_runs")
    op.drop_table("job_sources")
    op.drop_table("employers")
