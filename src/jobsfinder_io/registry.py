"""Small registry operations; the caller owns the transaction."""

import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobsfinder_io.persistence.models import Employer, JobSource, Posting, utc_now
from jobsfinder_io.sources.adapters import PROVIDERS, source_endpoint


class RegistryError(ValueError):
    """An expected input, identity, or lookup error."""


def normalize_domain(value: str | None) -> str | None:
    if value is None:
        return None
    domain = value.strip().lower().rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RegistryError("Invalid official domain") from exc
    if len(domain) > 253 or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
        domain,
    ):
        raise RegistryError("Use a domain such as example.com, without a URL or path")
    return domain


def add_employer(
    session: Session, name: str, official_domain: str | None = None
) -> Employer:
    name = name.strip()
    if not name:
        raise RegistryError("Employer name cannot be empty")
    employer = Employer(name=name, official_domain=normalize_domain(official_domain))
    session.add(employer)
    session.flush()
    return employer


def add_source(
    session: Session,
    employer_id: int,
    provider: str,
    board_identifier: str,
    careers_url: str,
    poll_interval_minutes: int = 60,
) -> JobSource:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise RegistryError("Unsupported provider")
    # Keep token case: Phase 1 has no evidence that differently cased boards
    # represent the same source. Strip surrounding whitespace only.
    board_identifier = board_identifier.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", board_identifier):
        raise RegistryError("Use an ATS board token, not a URL or empty value")
    careers_url = careers_url.strip()
    try:
        url = urlsplit(careers_url)
        valid_url = (
            url.scheme in {"https", "http"}
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not any(char.isspace() for char in careers_url)
        )
        _ = url.port
    except ValueError:
        valid_url = False
    if not valid_url:
        raise RegistryError("Careers URL must be an HTTP(S) URL without credentials")
    if poll_interval_minutes <= 0:
        raise RegistryError("Poll interval must be positive")
    if session.get(Employer, employer_id) is None:
        raise RegistryError(f"Employer {employer_id} does not exist")
    source = JobSource(
        employer_id=employer_id,
        provider=provider,
        board_identifier=board_identifier,
        careers_url=careers_url,
        api_endpoint=source_endpoint(provider, board_identifier),
        poll_interval_minutes=poll_interval_minutes,
    )
    try:
        # A savepoint lets callers recover from a duplicate without losing
        # unrelated work in their outer transaction. The unique key handles races.
        with session.begin_nested():
            session.add(source)
            session.flush()
    except IntegrityError as exc:
        existing = session.scalar(
            select(JobSource.id).where(
                JobSource.provider == provider,
                JobSource.board_identifier == board_identifier,
            )
        )
        if existing is not None:
            raise RegistryError(f"Source already registered as ID {existing}") from exc
        raise
    return source


def list_sources(session: Session) -> list[JobSource]:
    return list(session.scalars(select(JobSource).order_by(JobSource.id)))


def validate_source(
    session: Session,
    source_id: int,
    *,
    official_association_confirmed: bool,
    public_access_confirmed: bool,
) -> JobSource:
    """Record manual verification; this function never verifies URLs online."""
    if not official_association_confirmed or not public_access_confirmed:
        raise RegistryError("Confirm official employer association and public access")
    source = session.get(JobSource, source_id)
    if source is None:
        raise RegistryError(f"Source {source_id} does not exist")
    if source.status != "validated":
        source.status = "validated"
        source.validated_at = utc_now()
        session.flush()
    return source


def list_postings(session: Session, source_id: int | None = None) -> list[Posting]:
    query = select(Posting).order_by(Posting.id)
    if source_id is not None:
        if session.get(JobSource, source_id) is None:
            raise RegistryError(f"Source {source_id} does not exist")
        query = query.where(Posting.source_id == source_id)
    return list(session.scalars(query))
