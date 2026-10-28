"""Durable bounded work rotation and configurable discovery search breadth."""

from datetime import UTC, datetime

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from jobsfinder_io.discovery.network import DiscoveryError
from jobsfinder_io.persistence.models import Employer, TaskRun

US_REGIONS = (
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
    "District of Columbia",
)
COUNTRIES = (
    ("DE", "Germany"),
    ("IE", "Ireland"),
    ("GB", "United Kingdom"),
    ("AE", "United Arab Emirates"),
    ("CA", "Canada"),
    ("SG", "Singapore"),
    ("NL", "Netherlands"),
    ("SE", "Sweden"),
    ("FR", "France"),
    ("AT", "Austria"),
    ("CH", "Switzerland"),
    ("AU", "Australia"),
    ("NZ", "New Zealand"),
)
INDUSTRIES = (
    "startups",
    "government agencies",
    "universities",
    "insurance",
    "healthcare",
    "manufacturing",
    "finance",
    "retail",
    "logistics",
    "utilities",
    "consulting",
)
ROLES = (
    "junior graduate software developer",
    "backend Java Python developer",
    "full stack .NET application engineer",
    "integration developer tools engineer",
    "applied AI software engineer",
)


def _strings(config: dict, key: str, default: tuple) -> list[str]:
    values = config.get(key, list(default))
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value.strip() for value in values)
    ):
        raise DiscoveryError(f"invalid_search_{key}")
    return values


def search_plan(config: dict) -> list[tuple[str, str]]:
    """Return explicit queries plus an opt-in geographic/industry/role rotation.

    Each sweep reaches every state/DC and country while varying industry/role.
    Countries interleave with US regions so the international queue is not starved.
    Priority countries appear twice per sweep, additional countries once.
    """
    queries = config.get("queries", [])
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        raise DiscoveryError("invalid_search_queries")
    plan = [(q, config.get("country", "US")) for q in queries]
    if not config.get("rotate_breadth", False):
        return plan
    states = _strings(config, "us_regions", US_REGIONS)
    industries = _strings(config, "industries", INDUSTRIES)
    roles = _strings(config, "roles", ROLES)
    codes = _strings(config, "countries", tuple(code for code, _ in COUNTRIES))
    country_names = dict(COUNTRIES)
    if any(code not in country_names for code in codes):
        raise DiscoveryError("invalid_search_countries")
    international = [*codes, *(code for code in codes if code in dict(COUNTRIES[:6]))]
    for sweep in range(len(industries) * len(roles)):
        for index in range(max(len(states), len(international))):
            industry = industries[(sweep + index) % len(industries)]
            role = roles[(sweep // len(industries) + index) % len(roles)]
            if index < len(states):
                plan.append(
                    (f"{industry} employers {role} careers {states[index]} USA", "US")
                )
            if index < len(international):
                code = international[index]
                plan.append(
                    (
                        f"{industry} employers {role} careers {country_names[code]} English",
                        code,
                    )
                )
    return plan


def reserve_batch(
    engine: Engine, key: str, count: int, limit: int, now: datetime
) -> list[int]:
    """Advance before network access: interruption cannot starve later entries.

    Cursor is durable across daily runs/restarts. A failed batch is retried after
    cycling through the remaining queue; no records are discarded.
    """
    if not count or not limit:
        return []
    with Session(engine) as session, session.begin():
        session.execute(update(Employer).where(Employer.id == -1).values(name=""))
        row = session.scalar(select(TaskRun).where(TaskRun.task_key == key))
        offset = int(row.payload.get("offset", 0)) % count if row else 0
        selected = [(offset + index) % count for index in range(min(limit, count))]
        payload = {"offset": (offset + len(selected)) % count, "queue_size": count}
        if row is None:
            row = TaskRun(task_key=key, status="complete", payload=payload)
            session.add(row)
        else:
            row.payload = payload
        row.started_at = row.completed_at = now.astimezone(UTC)
    return selected
