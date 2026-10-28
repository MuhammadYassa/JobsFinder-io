"""Bounded exact-source qualification hints; no inferred skills or experience."""

import re

_REQUIRED_HEADING = re.compile(
    r"^(?:requirements|minimum qualifications|required qualifications|qualifications|"
    r"skills and experience|skills you.ll need to bring|what we.re looking for|what we are looking for|what you.ll bring|what you bring|"
    r"what you.ll need|what you need|about you|who you are|you could be a fit if)[:?]?$",
    re.I,
)
_PREFERRED_HEADING = re.compile(
    r"^(?:nice.to.haves?|preferred qualifications|preferred experience|preferred skills|"
    r"bonus(?: points)?|desirable)[:?]?$",
    re.I,
)
_OTHER_HEADING = re.compile(
    r"^(?:about us|about the company|benefits|what you.ll do|responsibilities|"
    r"about the role|the role|our benefits|compensation|a note on ai|our tech stack|what we offer|applying to .+)[:?]?$",
    re.I,
)
_EXPERIENCE = re.compile(
    r"\b(experience|years?|proficien\w*|familiar\w*|knowledge|expertise|hands.on)\b",
    re.I,
)
_PREFERRED = re.compile(
    r"\b(prefer\w*|nice.to.have|bonus|advantage|desirable|optional|a plus|ideally|not required|not mandatory|not necessary)\b",
    re.I,
)
_REQUIRED = re.compile(r"\b(required|must|minimum|at least|you have|you bring)\b", re.I)
_NOT_EXPERIENCE = re.compile(
    r"\b(?:salary range|base salary|cash compensation|compensation offered|pay range|"
    r"paid parental leave|health coverage|we don.t expect every|"
    r"you don.t need deep AI expertise for every role)\b",
    re.I,
)


def qualification_evidence(text: str, source_url: str) -> dict:
    """Keep exact clauses and section semantics, flag ambiguity instead of guessing.

    'required' means listed as a qualification, not proof that every item is a
    mandatory disqualifier. No numeric experience years are inferred.
    """
    result = {"required": [], "preferred": [], "unclassified": []}
    section = "unclassified"
    total = dict.fromkeys(result, 0)
    seen = set()
    for line in text.splitlines():
        clean = line.strip().lstrip("# ").rstrip(":")
        if _PREFERRED_HEADING.fullmatch(clean):
            section = "preferred"
            continue
        if _REQUIRED_HEADING.fullmatch(clean):
            section = "required"
            continue
        if _OTHER_HEADING.fullmatch(clean):
            section = "unclassified"
            continue
        if _NOT_EXPERIENCE.search(line):
            section = "unclassified"
            continue
        for clause in re.split(r"(?<=[.!?;])\s+", line):
            quote = clause.strip().lstrip("-• ")
            technical_qualification = section in {
                "required",
                "preferred",
            } and re.search(
                r"\b(?:built|shipped|coding|programming|Python|Java|TypeScript|Kotlin|SQL|React)\b",
                quote,
                re.I,
            )
            if (
                not quote
                or quote in seen
                or not (_EXPERIENCE.search(quote) or technical_qualification)
            ):
                continue
            seen.add(quote)
            preferred = bool(_PREFERRED.search(quote))
            required = bool(
                _REQUIRED.search(re.sub(r"\bnot required\b", "", quote, flags=re.I))
                or re.match(r"Have\s+\d", quote, re.I)
            )
            kind = (
                "unclassified"
                if preferred and required
                else "preferred"
                if preferred
                else "required"
                if required
                else section
            )
            total[kind] += 1
            if len(result[kind]) < 6 and len(quote) <= 1500:
                result[kind].append({"quote": quote, "source_url": source_url})
    result["truncated"] = any(total[kind] > len(result[kind]) for kind in total)
    return result


def reconcile_experience(value: dict, text: str, source_url: str) -> tuple[dict, dict]:
    """Complete missing fields transparently; never create a paraphrased fact."""
    hints = qualification_evidence(text, source_url)
    origins = {}
    for field, kind in (
        ("required_experience", "required"),
        ("preferred_experience", "preferred"),
    ):
        current = value[field]
        if isinstance(current, str) and _NOT_EXPERIENCE.search(current):
            raise ValueError("non_qualification_experience")
        # A substring of a clearly preferred clause cannot be a mandatory year
        # requirement. Preserve it in the preferred field instead.
        if (
            kind == "required"
            and current
            and any(current in item["quote"] for item in hints["preferred"])
            and not any(current in item["quote"] for item in hints["required"])
        ):
            if value["preferred_experience"] is None:
                value["preferred_experience"] = current
            value[field] = current = None
            if value.get("disposition") != "needs_review":
                value["disposition"] = "needs_review"
                value["requires_human_review"] = True
            value["uncertainty"].append(
                "Experience from a preferred clause is not a mandatory requirement."
            )
        if current is None and hints[kind]:
            item = hints[kind][0]
            value[field] = item["quote"]
            if item not in value["evidence"]:
                value["evidence"].append(item.copy())
            origins[kind] = "exact_source_fallback"
        else:
            origins[kind] = (
                "model" if current is not None else "not_explicitly_classified"
            )
    return hints, origins
