"""Conservative source-proof gate for hard exclusions, independent of LLM prose."""

import re

from jobsfinder_io.screening.evidence import qualification_evidence

_YEARS = re.compile(
    r"(?<![\w$])(\d{1,2})(?:\s*(?:\+|[-–]|to)\s*\d{0,2})?[\s-]+years?\b", re.I
)
_SOFT = re.compile(
    r"\b(?:preferred|preferably|ideally|bonus|advantage|nice.to.have|optional|"
    r"not required|not mandatory|not necessary|don.t need|do not need|flexible)\b",
    re.I,
)
_EXPERIENCE_REASON = re.compile(
    r"experience|years?|senior|background|qualifications?|level|entry.level", re.I
)
_EXPERIENCE_YEARS = re.compile(
    r"\byears?\b\s+(?:of\s+)?(?:[\w+-]+\s+){0,6}"
    r"(?:experience|in\b|building\b|as\b|developing\b)",
    re.I,
)


def hard_rejection_proofs(value: dict, text: str, source_url: str) -> list[dict]:
    """A title or a matching substring alone is not an exclusion requirement.

    Visa/start D have already passed their specialized corroboration checks.
    Experience above the early-career review range (0–3) needs an actual quoted
    required clause. This is a policy boundary, not an inferred candidate history.
    Ambiguous occupations and nonnumeric skill gaps require review.
    """
    evidence = value["evidence"]
    proofs = []
    if value["visa_class"] == "D":
        proofs.extend(
            {**item, "kind": "immigration"}
            for item in evidence
            if re.search(
                r"citizen|resident|clearance|sponsor|work authori|right to work",
                item["quote"],
                re.I,
            )
        )
    if value["start_class"] == "D":
        proofs.extend(
            {**item, "kind": "start_or_graduation"}
            for item in evidence
            if re.search(
                r"start|join|begin|graduate|internship will take place",
                item["quote"],
                re.I,
            )
        )
    if proofs:
        return proofs
    if not _EXPERIENCE_REASON.search(value["primary_reason"]):
        return []
    required = qualification_evidence(text, source_url)["required"]
    for item in evidence:
        quote = item["quote"]
        for clause in required:
            # Both the quoted evidence and the source qualification must carry
            # the number. A separate exact but unrelated quote is insufficient.
            matches = _YEARS.findall(quote)
            if (
                matches
                and _EXPERIENCE_YEARS.search(quote)
                and any(int(years) > 3 for years in matches)
                and (quote in clause["quote"] or clause["quote"] in quote)
                and not _SOFT.search(clause["quote"])
                and not _SOFT.search(quote)
            ):
                proofs.append({**item, "kind": "required_experience"})
    return proofs


def require_rejection_proof(value: dict, text: str, source_url: str) -> dict:
    if value["disposition"] != "reject":
        return value
    proofs = hard_rejection_proofs(value, text, source_url)
    if proofs:
        value["rejection_evidence"] = proofs
    else:
        value["model_primary_reason"] = value["primary_reason"]
        value["primary_reason"] = (
            "Needs review: quoted evidence does not establish a matching hard exclusion."
        )
        value["disposition"] = "needs_review"
        value["requires_human_review"] = True
        value["uncertainty"].append(
            "No independently corroborated hard-rejection requirement; do not discard this job."
        )
    return value
