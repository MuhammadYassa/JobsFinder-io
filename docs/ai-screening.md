# AI Screening and Eligibility (Proposed v0.1)

## Principle

**Deterministic code monitors; AI interprets.** The model must not be the primary source of job facts. It reasons over retrieved, attributable descriptions, role/applicant questions when accessible, and private eligibility policies; outputs typed decisions with evidence and uncertainty. Prefer **review** over incorrect rejection of possibly eligible roles.

## Pipeline

1. Normalize description while preserving the exact official URL, text evidence and content hash.
2. Run safe deterministic checks: clearly unrelated jobs, clear senior-only title with matching mandatory requirements, etc.; ambiguous titles remain.
3. Route plausible software-development roles by target location/country to US or international policy.
4. AI evaluates technical work, required vs preferred experience, authorization, date compatibility, and role relevance.
5. Validate AI output against a typed schema; reject malformed responses into `needs_review`, not `excluded`.
6. Save model/prompt/policy version, source hash, evidence, uncertainty, cost, and human override status.
7. A separate verified report step may draft letters from **confirmed** job facts and private candidate evidence.

## Decision schema (conceptual)

```json
{
  "relevance": "qualifies | stretch | needs_review | reject",
  "primary_reason": "text",
  "required_experience": "text | null",
  "preferred_experience": "text | null",
  "visa_class": "A | B | C | D | unknown",
  "visa_evidence": [{ "quote": "short source quote", "source_url": "..." }],
  "start_class": "A | B | C | D | unknown",
  "graduation_note": "text",
  "technologies": ["technology"],
  "uncertain_fields": ["field name"],
  "requires_human_review": true
}
```

This is an illustrative contract; actual schema validation, enums and nullability are implementation decisions. AI cannot simply assert that a visa category or exact publication date is verified.

## US policy (private configurable profile)

- Broad SWE/backend/full-stack/app/platform/developer-tools/data/AI-product development roles; substance over title.
- Typical required experience 0–2 years, plus internships/projects and flexible 1+; flexible 3 years only a labeled stretch. Don't reject required/preferred confusion.
- Explicit no sponsorship now/future, indefinite authorization, citizenship/permanent residence requirements, or disqualifying clearance/export restrictions => reject with quotes. Employer silence **does not** exclude.
- US classification: **A** explicit role-appropriate OPT/sponsorship welcome, **B** not specified/no exclusion, **C** OPT may be possible but later sponsorship constrained, **D** express exclusion; no sponsorship assumption.
- Future graduation, near-term starts, and mandatory graduation windows are evaluated independently; unknown starts remain concerns, not automatic rejection.

## International policy (private configurable profile)

- Country rules and employer role eligibility both matter. F-1 status does not confer foreign work rights.
- Visa **A** verified role/employer support or documented concrete viable route, **B** no exclusion but unconfirmed, **C** significant unresolved limitations, **D** explicit incompatibility.
- Start **A** confirmed compatible 2027 intake, **B** no explicit date/flexible, **C** apparently near-term uncertain, **D** explicit incompatible (unless documented exception).
- Never infer sponsorship from company-wide history or legal availability alone. Do not assert remote work is legally accessible from abroad without evidence.
- Prefer English-language listings; never assume local-language proficiency.

## AI quality safeguards

- Candidate profile is not part of public repository. Read locally protected config/secret store; send only information needed for the evaluation.
- Do not send keys, personal contact details, or unrelated files to models.
- Keep quotes brief and grounded to retrievable employer content; store URLs and detection evidence.
- Separate cheap broad relevance screening from more expensive detailed review; avoid repeat calls for unchanged content+policy versions.
- Keep a manually curated evaluation dataset: obvious matches, preferred/required confusion, ambiguous visas, immediate-start roles, 2027 graduation windows, varied software titles, and misleading analyst/QA roles.
- Measure **false negatives** first. Update prompts/tests when one is discovered; retain earlier outcomes for audit.
- Cost caps, token usage, timeouts and fallback-to-manual-review are required before continuous unattended AI use.

## Cover letters and reports

- Generate letters only from verified employer facts and truthful private profile/project evidence, 100–160 words if configured.
- User must approve any sending/submission separately; generation is not application.
- Daily reports distinguish newly detected, verified seven-day publication, freshness-uncertain, baseline backlog and rejected jobs without double counting.
