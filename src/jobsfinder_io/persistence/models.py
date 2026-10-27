"""The four application tables shared by the registry and Greenhouse collector."""

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store naive UTC in SQLite; require and return aware datetimes in Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamps must include a timezone")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class Employer(Base):
    __tablename__ = "employers"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="employer_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    official_domain: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
    sources: Mapped[list["JobSource"]] = relationship(back_populates="employer")


class JobSource(Base):
    __tablename__ = "job_sources"
    __table_args__ = (
        UniqueConstraint("provider", "board_identifier", name="uq_source_board"),
        CheckConstraint("provider = 'greenhouse'", name="supported_provider"),
        CheckConstraint("length(trim(board_identifier)) > 0", name="source_board"),
        CheckConstraint(
            "status IN ('candidate', 'validated', 'paused', 'error')",
            name="source_status",
        ),
        CheckConstraint("consecutive_failures >= 0", name="source_failures"),
        CheckConstraint("poll_interval_minutes > 0", name="source_interval"),
        CheckConstraint(
            "status != 'validated' OR validated_at IS NOT NULL",
            name="source_validation_time",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employer_id: Mapped[int] = mapped_column(ForeignKey("employers.id"))
    provider: Mapped[str]
    board_identifier: Mapped[str]
    careers_url: Mapped[str]
    api_endpoint: Mapped[str]
    status: Mapped[str] = mapped_column(default="candidate", server_default="candidate")
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    poll_interval_minutes: Mapped[int] = mapped_column(default=60, server_default="60")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    employer: Mapped[Employer] = relationship(back_populates="sources")
    postings: Mapped[list["Posting"]] = relationship(back_populates="source")
    poll_runs: Mapped[list["PollRun"]] = relationship(back_populates="source")


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_posting_id", name="uq_posting_identity"
        ),
        CheckConstraint(
            "length(trim(external_posting_id)) > 0", name="posting_identity"
        ),
        CheckConstraint(
            "status IN ('active', 'missing_pending', 'closed', 'unknown')",
            name="posting_status",
        ),
        CheckConstraint("last_seen_at >= first_seen_at", name="posting_seen_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id"))
    external_posting_id: Mapped[str]
    external_requisition_id: Mapped[str | None]
    title: Mapped[str]
    canonical_job_url: Mapped[str]
    apply_url: Mapped[str]
    description_text: Mapped[str]
    source_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    date_provenance: Mapped[str]
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(default="unknown", server_default="unknown")
    source: Mapped[JobSource] = relationship(back_populates="postings")


class PollRun(Base):
    __tablename__ = "poll_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'complete_success', 'partial', 'failed')",
            name="poll_status",
        ),
        CheckConstraint("post_count IS NULL OR post_count >= 0", name="poll_count"),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="poll_http"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="poll_time_order"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(default="running", server_default="running")
    http_status: Mapped[int | None]
    post_count: Mapped[int | None]
    error_code: Mapped[str | None]
    source: Mapped[JobSource] = relationship(back_populates="poll_runs")
