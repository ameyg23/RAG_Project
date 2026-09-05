# Demo Knowledge-Base Content

Self-authored, entirely fictional content (ROADMAP.md Phase 4) — **not**
real information about any real company, product, or person. Written
specifically to ground the demo knowledge base described in
`docs/REQUIREMENTS.md` (FR-001–004).

"Acme Software Inc." and its product "Beacon" are placeholder fictions
invented for this demo. Any resemblance to a real company or product is
coincidental.

## Files

| File | Topic |
|---|---|
| `01_employee_handbook.md` | HR policy: hours, remote work, PTO, benefits, code of conduct, expenses |
| `02_product_faq.md` | Beacon product FAQ: features, pricing tiers, integrations, data export, security/compliance, support |
| `03_onboarding_guide.md` | New-employee onboarding: pre-day-one, first day, first week, who to contact |
| `04_security_policy.md` | Information security policy: passwords, 2FA, device use, data classification, incident reporting, remote-work security |

## Suggested Questions

See `suggested_questions.json` — 5 curated questions (FR-003), each
verified answerable from exactly one document above. Delivery mechanism to
the frontend (a new API field vs. a static frontend list) is intentionally
undecided here — that plumbing choice belongs to Phase 16 (Chat UI), not
this content-authoring phase. Whichever Phase 16 chooses, it must read from
this file rather than re-deriving/re-guessing the questions.

## How this feeds later phases

These files are the literal input to `backend/scripts/seed_demo_kb.py`
(Phase 15) — they are ingested through the real pipeline
(`docs/RAG_PIPELINE.md`), not paraphrased into hardcoded strings elsewhere.
Phase 18's evaluation dataset (`evaluation/dataset/demo_kb_cases.json`) must
be written against the actual content of these files once ingestion exists.
