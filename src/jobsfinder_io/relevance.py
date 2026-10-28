"""Conservative software relevance hints, without eligibility or AI judgments."""

import re

_SOFTWARE = re.compile(
    r"\b(software|backend|back.end|full.stack|front.end|developer|programming|"
    r"python|java|typescript|javascript|spring boot|react|c\+\+|c#|\.net|"
    r"application engineer|integration engineer|data engineer|machine learning engineer|"
    r"ai engineer|devops|developer tools|firmware|embedded|sql)\b",
    re.I,
)
_UNRELATED = re.compile(
    r"\b(account executive|sales representative|recruiter|human resources|nurse|"
    r"physician|accountant|legal counsel|warehouse associate|truck driver|"
    r"customer service representative|marketing manager|office manager|"
    r"executive assistant|cashier|retail associate|security guard|"
    r"talent acquisition partner|talent acquisition sourcer|recruiting sourcer)\b",
    re.I,
)
_CODING = re.compile(
    r"\b(python|java|typescript|javascript|programming|coding|spring boot|"
    r"backend|full.stack|front.end|react|sql)\b|\.net\b|c\+\+|c#",
    re.I,
)
_US = re.compile(
    r"\b(united states|usa|us|u\.s\.?|new york|san francisco|seattle|boston|"
    r"austin|chicago|california|texas|washington|massachusetts|virginia)\b"
    r"|,\s*(NY|CA|TX|WA|MA|VA|CO|IL|FL|GA|NC|PA|NJ|OH|OR|AZ|UT)\b",
    re.I,
)
_COUNTRIES = (
    "Germany",
    "Ireland",
    "United Kingdom",
    "UK",
    "United Arab Emirates",
    "UAE",
    "Canada",
    "Singapore",
    "Netherlands",
    "Sweden",
    "France",
    "Austria",
    "Switzerland",
    "Australia",
    "New Zealand",
    "India",
    "Pakistan",
    "Poland",
    "Spain",
    "Portugal",
    "Japan",
    "Brazil",
    "Mexico",
    "Israel",
    "South Africa",
    "South Korea",
    "Republic of Korea",
    "Malaysia",
    "China",
    "Philippines",
    "Latvia",
    "Thailand",
    "Vietnam",
    "Indonesia",
    "Cambodia",
    "Taiwan",
    "Hong Kong",
    "Finland",
    "Denmark",
    "Norway",
    "Belgium",
    "Italy",
    "Czechia",
    "Czech Republic",
    "Romania",
    "Estonia",
    "Lithuania",
    "Bulgaria",
    "Turkey",
)


def assess_relevance(title: str, description: str) -> str:
    """Retain uncertainty; exclusion requires a clearly unrelated occupation."""
    if _SOFTWARE.search(title):
        return "software evidence"
    if _UNRELATED.search(title) and not _CODING.search(description):
        return "unrelated"
    if _SOFTWARE.search(description):
        return "software evidence"
    return "uncertain relevance — review manually"


def location_group(locations: str) -> tuple[str, str]:
    """Route explicit geography only; remote alone does not establish a country."""
    countries = [
        country
        for country in _COUNTRIES
        if re.search(r"\b" + re.escape(country) + r"\b", locations, re.I)
    ]
    if re.search(r"\b(England|Scotland|Wales|Northern Ireland)\b", locations, re.I):
        countries = [
            country
            for country in countries
            if country != "Ireland"
            or not re.search(r"\bNorthern Ireland\b", locations, re.I)
        ]
        if "United Kingdom" not in countries:
            countries.append("United Kingdom")
    us = bool(_US.search(locations))
    foreign_city_hint = re.search(
        r"\b(London|Berlin|Dublin|Dubai|Toronto|Vancouver|Paris|Amsterdam|Sydney|Seoul)\b",
        locations,
        re.I,
    )
    if us and foreign_city_hint and not countries:
        return "unknown", "Mixed or ambiguous geography; inspect official posting"
    if us and countries:
        return "unknown", "Multiple countries (including US): " + ", ".join(countries)
    if us:
        return "us", "United States (location evidence)"
    if countries:
        return "international", ", ".join(countries)
    return "unknown", "Country unverified; inspect official posting"


def requirement_excerpts(description: str) -> list[str]:
    """Return exact, bounded source excerpts rather than invented requirements."""
    parts = re.split(r"\n+|(?<=[.!?])\s+", description)
    qualifications = [
        part.strip()
        for part in parts
        if re.search(
            r"\b(years?|experience|preferred|require[ds]?|qualifications?|graduate)\b",
            part,
            re.I,
        )
    ]
    numeric_years = [
        part
        for part in qualifications
        if re.search(r"\d[^.!?\n]{0,15}\byears?\b", part, re.I)
    ]
    selected = [
        part.strip()
        for part in parts
        if _SOFTWARE.search(part)
        or re.search(
            r"\b(years?|experience|preferred|require[ds]?|graduate)\b", part, re.I
        )
    ]
    prioritized = list(dict.fromkeys([*numeric_years, *qualifications, *selected]))
    return [part[:500] for part in prioritized[:4]]
