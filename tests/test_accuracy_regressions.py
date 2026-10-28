"""Synthetic hard cases, independently labeled before live holdout predictions."""

import pytest
from test_screening import output

from jobsfinder_io.screening import pipelines_for, validate_result
from jobsfinder_io.screening.batch import validate_batch
from jobsfinder_io.screening.context import validate_context
from jobsfinder_io.screening.evidence import qualification_evidence

URL = "https://example.test/job"


@pytest.mark.parametrize(
    "location,expected",
    [
        (
            "Hybrid; New York, New York; San Francisco, California; United States",
            ("us",),
        ),
        ("Remote (Canada)", ("international",)),
        ("London, UK", ("international",)),
        ("Global Remote; US; remote", ("us", "international")),
        ("Remote; United States; Canada", ("us", "international")),
        ("Remote", ("us", "international")),
    ],
)
def test_geographic_policy_routing(location, expected):
    assert pipelines_for(location) == expected


@pytest.mark.parametrize(
    "text,claimed,expected",
    [
        ("Visa sponsorship is not available.", "A", "B"),
        ("You will create sponsored content.", "C", "B"),
        ("Germany has a skilled worker visa route.", "C", "B"),
        ("Visa sponsorship is available for this position.", "A", "A"),
        (
            "We accept OPT applicants but cannot offer future H-1B sponsorship.",
            "C",
            "C",
        ),
        (
            "This position is generally not eligible for new visa sponsorship. At our discretion, we may sponsor existing visa transfers.",
            "D",
            "C",
        ),
        ("Must already have independent work authorization in Canada.", "D", "D"),
    ],
)
def test_immigration_claim_needs_relevant_semantic_evidence(text, claimed, expected):
    value = output(
        visa_class=claimed,
        preferred_experience=None,
        evidence=[{"quote": text, "source_url": URL}],
    )
    result = validate_result(value, text, URL)
    assert result["visa_class"] == expected
    if expected in {"B", "C"}:
        assert result["requires_human_review"]


def test_missing_experience_filled_with_exact_clauses_and_origins():
    text = "Requirements\nExperience building Python APIs.\nNice to have\nExperience with Terraform is an advantage."
    job = {"id": 1, "text": text, "url": URL, "pipelines": ["us"]}
    value = output(
        preferred_experience=None,
        evidence=[{"quote": "Experience building Python APIs.", "source_url": URL}],
    )
    valid, invalid = validate_batch(
        [{"job_id": 1, "evaluations": [{"pipeline": "us", "result": value}]}], [job], {}
    )
    assert not invalid
    result = valid[(1, "us")]
    assert result["required_experience"] == "Experience building Python APIs."
    assert (
        result["preferred_experience"] == "Experience with Terraform is an advantage."
    )
    assert set(result["experience_origins"].values()) == {"exact_source_fallback"}


def test_preferred_years_are_not_mandatory_and_do_not_reject():
    text = "Requirements\nExperience building APIs.\nPreferred experience\nThree years of experience is preferred."
    job = {"id": 1, "text": text, "url": URL, "pipelines": ["us"]}
    value = output(
        disposition="reject",
        primary_reason="Missing preferred experience.",
        required_experience="Three years",
        preferred_experience=None,
        evidence=[
            {"quote": "Three years of experience is preferred.", "source_url": URL}
        ],
    )
    valid, _ = validate_batch(
        [{"job_id": 1, "evaluations": [{"pipeline": "us", "result": value}]}], [job], {}
    )
    result = valid[(1, "us")]
    assert result["required_experience"] == "Experience building APIs."
    assert result["preferred_experience"] == "Three years"
    # The model's unsupported preferred-only rejection must remain reviewable.
    assert result["disposition"] == "needs_review"


def test_malformed_result_stays_pending_instead_of_crashing():
    job = {"id": 1, "text": "Python", "url": URL, "pipelines": ["us"]}
    valid, invalid = validate_batch(
        [
            {
                "job_id": 1,
                "evaluations": [{"pipeline": "us", "result": {"evidence": [1]}}],
            }
        ],
        [job],
        {},
    )
    assert not valid and invalid[1] == "invalid_or_ungrounded_result"


def test_ambiguous_experience_and_bounded_extraction():
    hints = qualification_evidence(
        "Experience building APIs would be helpful.\n" * 20, URL
    )
    assert not hints["required"]
    assert len(hints["unclassified"]) == 1


def test_explicit_winter_internship_interval_precedes_availability():
    quote = "This internship will take place from Jan 25 - Apr 16 and you will need to work in our office during this time."
    text = "Software Engineer Intern (Winter 2027)\n" + quote
    value = output(
        disposition="reject",
        start_class="D",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(
        value, text, URL, available_from="2027-06-01", graduation_year=2027
    )
    assert result["disposition"] == "reject" and result["start_class"] == "D"


@pytest.mark.parametrize(
    "heading", ["What We Are Looking For", "SKILLS YOU'LL NEED TO BRING:"]
)
def test_real_heading_variants_and_compensation_boundary(heading):
    hints = qualification_evidence(
        heading
        + "\nExperience building Python services.\nNice to Haves\nExperience with Terraform.\nThe estimated base salary range is $100,000 per year.",
        URL,
    )
    assert hints["required"][0]["quote"] == "Experience building Python services."
    assert hints["preferred"][0]["quote"] == "Experience with Terraform."
    assert not any(
        "salary" in q["quote"]
        for group in ("required", "preferred", "unclassified")
        for q in hints[group]
    )


@pytest.mark.parametrize(
    "quote",
    [
        "The estimated base salary range is $100,000 per year.",
        "You don’t need deep AI expertise for every role, but we expect curiosity.",
    ],
)
def test_non_qualification_experience_invalidates_result(quote):
    job = {"id": 1, "text": quote, "url": URL, "pipelines": ["us"]}
    value = output(
        preferred_experience=quote, evidence=[{"quote": quote, "source_url": URL}]
    )
    valid, invalid = validate_batch(
        [{"job_id": 1, "evaluations": [{"pipeline": "us", "result": value}]}], [job], {}
    )
    assert not valid and invalid[1] == "invalid_or_ungrounded_result"


@pytest.mark.parametrize(
    "text,reason,visa",
    [
        (
            "Analytics Engineer\nExperience designing production-grade data models and SQL pipelines.",
            "Analytics engineering does not match the software engineering profile.",
            "B",
        ),
        (
            "Software Engineer\nProduction AI systems experience is expected.",
            "Senior AI role exceeds entry-level background.",
            "B",
        ),
        (
            "Software Engineer\nNew visa sponsorship is generally restricted; transfers may be considered.",
            "Explicit visa sponsorship restriction.",
            "C",
        ),
    ],
)
def test_unresolved_immigration_or_inferred_seniority_is_reviewable(text, reason, visa):
    quote = text.splitlines()[1]
    value = output(
        disposition="reject",
        primary_reason=reason,
        visa_class=visa,
        preferred_experience=None,
        required_experience=quote,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, text, URL)
    assert result["disposition"] == "needs_review"


def test_senior_title_without_hard_requirement_remains_reviewable():
    text = "Senior Software Engineer\nProduction systems experience required."
    value = output(
        disposition="reject",
        primary_reason="Senior role exceeds candidate background.",
        preferred_experience=None,
        required_experience="Production systems experience required.",
        evidence=[
            {"quote": "Production systems experience required.", "source_url": URL}
        ],
    )
    assert validate_result(value, text, URL)["disposition"] == "needs_review"


@pytest.mark.parametrize(
    "reason",
    [
        "Not enough experience.",
        "Career path mismatch.",
        "Lacks domain expertise.",
        "Not qualified.",
    ],
)
def test_every_rejection_needs_matching_hard_proof_regardless_of_reason(reason):
    quote = "Build Python software and SQL pipelines."
    value = output(
        disposition="reject",
        primary_reason=reason,
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, "Software Analyst\n" + quote, URL)
    assert result["disposition"] == "needs_review"
    assert result["model_primary_reason"] == reason


def test_quoted_required_years_prove_hard_exclusion_but_preferred_do_not():
    quote = "Required: 8+ years of professional software engineering experience."
    value = output(
        disposition="reject",
        primary_reason="Eight years exceeds entry-level experience.",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, "Software Engineer\n" + quote, URL)
    assert result["disposition"] == "reject"
    assert result["rejection_evidence"] == [
        {"quote": quote, "source_url": URL, "kind": "required_experience"}
    ]


def test_uncertain_timing_does_not_erase_proven_experience_exclusion():
    quote = "Required: 8+ years of software engineering experience."
    value = output(
        disposition="reject",
        primary_reason="Requires eight years of experience.",
        start_class="C",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, "Software Engineer\n" + quote, URL)
    assert result["start_class"] == "B" and result["disposition"] == "reject"


def test_imperative_have_years_is_required_not_company_tenure():
    quote = "Have 5+ years of hands-on experience in corporate security."
    hints = qualification_evidence(quote, URL)
    assert hints["required"][0]["quote"] == quote


def test_unquoted_sponsorship_exception_in_source_cannot_be_hidden():
    quote = "This position is not eligible for new visa sponsorship."
    value = output(
        disposition="reject",
        visa_class="D",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(
        value,
        quote + "\nAt our discretion, we may sponsor existing visa transfers.",
        URL,
    )
    assert result["visa_class"] == "C" and result["disposition"] == "needs_review"


def test_us_authorization_requirement_does_not_establish_opt_ban():
    quote = "Existing work authorization required."
    value = output(
        disposition="reject",
        visa_class="D",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, quote, URL, pipeline="us")
    assert result["visa_class"] == "C" and result["disposition"] == "needs_review"


def test_north_america_does_not_establish_canada():
    value = output(country="Canada")
    result = validate_context(
        value,
        {
            "title": "Software Engineer",
            "locations": "North America; United States; Remote",
        },
        {},
    )
    assert result["country"] is None


def test_international_result_does_not_claim_us_as_foreign_country():
    value = output(country="United States")
    result = validate_context(
        value,
        {"title": "Software Engineer", "locations": "United States; Canada"},
        {},
        pipeline="international",
    )
    assert result["country"] is None


def test_optional_web_experience_cannot_prove_required_android_fit():
    text = "SKILLS YOU'LL NEED TO BRING\nYou have built and shipped Android apps with Kotlin.\nWeb experience (TypeScript, React, Node) is welcome but not required."
    quote = "Web experience (TypeScript, React, Node) is welcome but not required."
    job = {
        "id": 1,
        "title": "Software Engineer Android",
        "locations": "United States",
        "text": text,
        "url": URL,
        "pipelines": ["us"],
    }
    value = output(
        required_experience=quote,
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    valid, invalid = validate_batch(
        [{"job_id": 1, "evaluations": [{"pipeline": "us", "result": value}]}], [job], {}
    )
    assert not invalid
    result = valid[(1, "us")]
    assert result["disposition"] == "needs_review"
    assert (
        result["required_experience"]
        == "You have built and shipped Android apps with Kotlin."
    )
    assert result["preferred_experience"] == quote


def test_summer_internship_is_not_confirmed_full_time_eligibility():
    value = output()
    result = validate_context(
        value,
        {
            "title": "Software Engineer Intern (Summer 2027)",
            "locations": "United States",
        },
        {"us": {"target": "First full-time professional engineering role"}},
    )
    assert result["disposition"] == "needs_review"


def test_non_timing_quote_cannot_prove_compatible_start():
    quote = "Previous internship experience."
    value = output(
        start_class="A",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    result = validate_result(value, quote, URL)
    assert result["start_class"] == "B" and result["disposition"] == "needs_review"


def test_benefit_tenure_is_not_required_professional_experience():
    quote = "You have a paid month off after 4 years."
    value = output(
        disposition="reject",
        primary_reason="Requires four years of experience.",
        preferred_experience=None,
        evidence=[{"quote": quote, "source_url": URL}],
    )
    assert (
        validate_result(value, "Requirements\n" + quote, URL)["disposition"]
        == "needs_review"
    )
