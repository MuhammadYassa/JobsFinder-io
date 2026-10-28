"""Conservative source geography and private search-goal checks."""

import re


def validate_context(
    result: dict, job: dict, profile: dict, *, pipeline: str | None = None
) -> dict:
    country = result["country"]
    aliases = {
        "united states": r"\b(?:United States|US|USA|U\.S\.)\b",
        "us": r"\b(?:United States|US|USA|U\.S\.)\b",
        "united kingdom": r"\b(?:United Kingdom|UK|England|Scotland|Wales)\b",
        "uk": r"\b(?:United Kingdom|UK|England|Scotland|Wales)\b",
    }
    if country and not re.search(
        aliases.get(country.lower(), r"\b" + re.escape(country) + r"\b"),
        job.get("locations", ""),
        re.I,
    ):
        result["country"] = None
        result["uncertainty"].append(
            "Country is not explicit in the supplied location; regional coverage does not establish a country."
        )
        result["requires_human_review"] = True
    if (
        pipeline == "international"
        and result["country"]
        and result["country"].lower() in {"united states", "us", "usa"}
    ):
        result["country"] = None
        result["uncertainty"].append(
            "The international policy has no explicitly selected foreign country; confirm the applicable location."
        )
        result["requires_human_review"] = True
    target = " ".join(
        str(profile.get(p, {}).get("target", "")) for p in ("us", "international")
    )
    if (
        re.search(r"\bintern(?:ship)?\b", job.get("title", ""), re.I)
        and re.search(r"first.full.time|first.*professional", target, re.I)
        and result["disposition"] in {"recommend", "stretch"}
    ):
        result["model_primary_reason"] = result["primary_reason"]
        result["primary_reason"] = (
            "Needs review: internship/student eligibility and fit with the private full-time search goal require confirmation."
        )
        result["disposition"] = "needs_review"
        result["uncertainty"].append(
            "An internship is not a confirmed first full-time professional role."
        )
        result["requires_human_review"] = True
    return result
