# Zero-Cost Deployment Plan

Free-tier facts below were verified via web search during planning (2026-09).
Free tiers change over time — re-verify against each provider's current
pricing page before a real launch, rather than trusting these numbers
indefinitely (see the note on Groq limits in particular).

## Frontend — Cloudflare Pages

- **Free tier:** unlimited bandwidth, 500 builds/month, unlimited static
  requests, global 300-city CDN, free SSL, no credit card required.
- **Build process:** `vite build` → static `dist/`; Cloudflare Pages
  auto-detects the Vite framework preset from the connected Git repo and
  builds on every push.
- **Environment configuration:** `VITE_API_BASE_URL` set as a Cloudflare
  Pages build-time environment variable, pointing at the deployed Render
  backend URL. Not a secret — it's a public URL baked into the static
  bundle.

**Why this provider:** ADR-09 — the only free static host with no bandwidth
cap, important for a project that might be shared/linked publicly without
risking a bandwidth-based interruption.

## Backend — Render (Free Web Service)

- **Free tier:** 750 free instance-hours/month, native Python buildpack (no
  Dockerfile required), no credit card required.
- **Cold start:** free web services **sleep after 15 minutes of
  inactivity**; the next request pays a **30–60 second cold-start penalty**
  while the service spins back up. This is the single biggest latency
  characteristic to design the UI around (`docs/UI_UX.md` §1, §10).
- **Build process:** `pip install -r requirements.txt`; start command
  `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- **Environment configuration:** secrets (`GROQ_API_KEY`, `QDRANT_URL`,
  `QDRANT_API_KEY`) set via Render's dashboard environment-variable UI,
  never committed to the repository.

**Why this provider:** ADR-10 — simplest Git-integrated Python deploy with
no card required; disk is ephemeral (wiped on redeploy), which is why no
persistent state lives on the backend filesystem (ADR-11, ADR-12).

## Vector Storage — Qdrant Cloud (Free Tier)

- **Free tier:** one cluster, 0.5 vCPU / 1GB RAM / 4GB disk — comfortably
  enough for this project's 384-dim vectors at small scale (the free tier
  supports roughly 1M vectors at 768-dim; this project uses fewer
  dimensions and a much smaller corpus). No credit card required;
  permanently free, not a trial.
- **Persistence:** genuinely persists independent of the backend's restart/
  redeploy cycle — this is *why* Qdrant Cloud was chosen over a
  self-hosted Chroma/FAISS file on Render's ephemeral disk (ADR-07).
- **Free-tier limitation — the biggest real risk in this plan:** a free
  Qdrant cluster **suspends after 7 days of inactivity** and is **deleted
  after 28 days of inactivity**. For a low-traffic portfolio demo, this is
  a realistic scenario, not a hypothetical.
  - **Recovery procedure:** re-run `backend/scripts/seed_demo_kb.py`
    (`docs/DOCUMENT_PROCESSING.md`) against a reactivated or newly created
    free cluster to repopulate the demo KB. User-uploaded knowledge bases
    lost this way are simply gone — acceptable, since uploads were never
    represented to users as permanently retained (`docs/REQUIREMENTS.md`
    §12).
  - **Deliberately not mitigated by a keep-alive ping:** a scheduled uptime
    ping would count as "activity" and prevent suspension, but adds a
    scheduling dependency disproportionate to a portfolio project. The
    accepted mitigation is the one-command reseed script plus this
    documentation, not automation.

## Document Storage

No provider is used (ADR-11). Raw uploaded files are transient — deleted
from the backend's temp directory once ingestion completes or fails.
$0, and no persistence risk to document, since nothing is stored beyond
extracted chunks (which live in Qdrant, covered above).

## LLM — Groq

- **Provider / model:** Groq, `llama-3.3-70b-versatile`.
- **Free limits (as verified 2026-09):** no credit card required; roughly
  30 requests/minute and 14,400 requests/day at the organization level,
  with tighter model-specific daily/token caps for larger models. **These
  numbers drift — re-verify at
  [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits)
  before relying on them for a real launch**, rather than treating today's
  figures as permanently fixed.
- **Rate-limit / quota behavior:** exceeding limits returns HTTP 429 from
  Groq, which the backend maps to the sanitized `502 LLM_UNAVAILABLE`
  response defined in `docs/API.md` — never a raw provider error.

**Why this provider:** ADR-08 — no card required, fast inference, and
per-minute limits better suited to interactive chat than the stricter daily
caps observed on comparable free-tier Gemini models during this project's
provider research.

## Cross-Cutting Concerns

**Cold starts:** only the Render backend cold-starts; Cloudflare Pages is
always-on static hosting with no equivalent delay. UI mitigation is owned
by `docs/UI_UX.md` (distinct "waking up" messaging).

**Persistence risks:** the Qdrant 7-day/28-day inactivity suspension
(above) is the single biggest "this looks broken but isn't" risk in this
architecture. Mitigation is documentation + a one-command reseed script,
deliberately not an automated keep-alive.

**CORS:** the backend's allowed origin (`CORS_ALLOWED_ORIGIN`, see
`docs/ENVIRONMENT.md`) must be updated to match whichever Cloudflare Pages
URL (or custom domain) is actually assigned — a manual one-line config step
performed once, immediately after the first frontend deploy.

**Environment variables:** full list in `docs/ENVIRONMENT.md`.

**Secret management:** every secret lives only in (a) the issuing
provider's own dashboard (where the key value is generated — Groq, Qdrant),
and (b) Render's environment-variable dashboard. Nothing secret is ever
committed to git or present in the Cloudflare Pages build output.

## Deployment Sequence

1. Create a Qdrant Cloud free cluster; record its URL and API key.
2. Create a Groq account and generate an API key (no card required).
3. Deploy the backend to Render; set `GROQ_API_KEY`, `QDRANT_URL`,
   `QDRANT_API_KEY` as environment variables; verify `GET /health` returns
   `"status": "ok"`.
4. Run `backend/scripts/seed_demo_kb.py` once against the live backend/Qdrant
   cluster to populate the demo knowledge base.
5. Deploy the frontend to Cloudflare Pages with `VITE_API_BASE_URL` set to
   the deployed Render backend's URL.
6. Update the backend's `CORS_ALLOWED_ORIGIN` environment variable to the
   final Cloudflare Pages URL and redeploy the backend.

## How to Replace an API Key

Rotate the key in the issuing provider's dashboard (Groq or Qdrant), then
update the corresponding environment variable in Render's dashboard. Render
redeploys automatically on an environment-variable change (or trigger a
manual redeploy). **No code change is required anywhere** — this follows
directly from ADR-15's backend-only secret pattern.

## How to Avoid Accidental Billing

Never add a payment method to any of the four services used here (Render,
Groq, Qdrant Cloud, Cloudflare Pages) for this project — every free tier
referenced above explicitly requires no card. If any provider ever prompts
for card entry to continue using a feature this plan relies on, treat that
as a signal to stop and re-evaluate the plan, not to proceed.

## Acceptance Criteria Check

- **Every external service has a documented cost model:** ✓ (Cloudflare
  Pages, Render, Qdrant Cloud, Groq — each above).
- **Persistence is explicitly addressed:** ✓ (Qdrant persistence + its
  suspension risk; ephemeral backend disk; transient raw files).
- **No paid service is required for V1:** ✓ — all four services are used
  at their no-card free tier.
- **API keys are not exposed:** ✓ — backend-only environment variables
  (ADR-15), never in frontend build output.
- **Deployment can be reproduced from the documentation:** ✓ — the ordered
  six-step sequence above is sufficient to redeploy from scratch.
