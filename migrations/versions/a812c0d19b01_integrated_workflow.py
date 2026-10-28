"""Durable screening, discovery, delivery and scheduling.

Revision ID: a812c0d19b01
Revises: e49ff864f16a
"""

import sqlalchemy as sa
from alembic import op

revision = "a812c0d19b01"
down_revision = "e49ff864f16a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("supported_provider", type_="check")
        batch.create_check_constraint(
            "supported_provider",
            "provider IN ('greenhouse', 'lever', 'lever_eu', 'ashby')",
        )
    op.add_column(
        "postings",
        sa.Column("locations", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "postings", sa.Column("last_changed_at", sa.DateTime(), nullable=True)
    )
    op.execute("UPDATE postings SET last_changed_at = first_seen_at")
    with op.batch_alter_table("postings") as batch:
        batch.alter_column(
            "last_changed_at", existing_type=sa.DateTime(), nullable=False
        )
    op.add_column(
        "postings",
        sa.Column(
            "discovery_kind", sa.String(), nullable=False, server_default="baseline"
        ),
    )
    op.add_column(
        "postings",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "screening_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "posting_id", sa.Integer(), sa.ForeignKey("postings.id"), nullable=False
        ),
        *[
            sa.Column(name, sa.String(), nullable=False)
            for name in (
                "content_hash",
                "profile_hash",
                "policy_version",
                "prompt_version",
                "model",
                "stage",
                "pipeline",
                "disposition",
            )
        ],
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_screening_results_posting_id", "screening_results", ["posting_id"]
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "posting_id", sa.Integer(), sa.ForeignKey("postings.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pipeline", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("artifact_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "posting_id", "revision", "pipeline", "channel", name="uq_delivery_identity"
        ),
    )
    op.create_table(
        "discovery_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_url", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_key", sa.String(), unique=True, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    # A downgrade must not silently destroy sources unsupported by the old schema.
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT count(*) FROM job_sources WHERE provider != 'greenhouse'")
    ):
        raise RuntimeError(
            "Remove non-Greenhouse sources explicitly before downgrading"
        )
    for table in ("task_runs", "discovery_attempts", "deliveries", "screening_results"):
        op.drop_table(table)
    with op.batch_alter_table("postings") as batch:
        for name in ("locations", "last_changed_at", "discovery_kind", "revision"):
            batch.drop_column(name)
    with op.batch_alter_table("job_sources") as batch:
        batch.drop_constraint("supported_provider", type_="check")
        batch.create_check_constraint("supported_provider", "provider = 'greenhouse'")
