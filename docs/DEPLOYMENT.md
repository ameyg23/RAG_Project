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
  Pages build-time environment variable, pointing at the deployed backend
  URL — currently the Cloud Run service's `*.run.app` URL (see "Backend —
  Google Cloud Run" below; was the Render URL prior to ADR-19). Not a
  secret — it's a public URL baked into the static bundle.

**Why this provider:** ADR-09 — the only free static host with no bandwidth
cap, important for a project that might be shared/linked publicly without
risking a bandwidth-based interruption.

## Backend — Render (Free Web Service) — SUPERSEDED, see Cloud Run below

**Status (2026-09): superseded by Google Cloud Run (ADR-19).** Render's
free-tier 512MB RAM ceiling proved insufficient for this backend's real
request load — confirmed via repeated live testing, not assumed:
`GET /health` reliably returned `200`, but a real `POST /chat` request
(which loads `BAAI/bge-small-en-v1.5` via `sentence-transformers`/CPU-torch
to embed the query) reliably 502'd shortly after, followed by an instance
restart. This happened **even after** ADR-17's reranker was fully reverted
to reduce memory pressure — proving the embedding model alone, not the
reranker, was already enough to exceed 512MB under real inference load. See
ADR-19 for the full evidence trail and provider comparison. This section is
kept, not deleted, because `render.yaml` remains in the repository as a
legitimate fallback if the user ever chooses to pay for Render's Standard
tier (2GB+ RAM) instead of using Cloud Run's free tier — the instructions
below still apply verbatim to that paid path.

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

**Why this provider (historical — see ADR-19 for why it was replaced):**
ADR-10 — simplest Git-integrated Python deploy with no card required; disk
is ephemeral (wiped on redeploy), which is why no persistent state lives on
the backend filesystem (ADR-11, ADR-12).

## Backend — Google Cloud Run (current)

**Free tier:** ~180,000 vCPU-seconds and ~360,000 GiB-seconds of compute
per month, 2 million requests/month, no credit card required to use the
free tier. Unlike Render free's fixed 512MB ceiling, Cloud Run lets you
configure container memory up to 32GB — the dimension that actually broke
on Render (see ADR-19). This project uses a small fraction of that ceiling
(1GiB recommended below), leaving real headroom instead of running at the
edge of what OOM-crashed before.

- **Build process:** Cloud Run's **"Continuously deploy from a
  repository"** flow triggers a Cloud Build that reads `backend/Dockerfile`
  (added for this migration — see `backend/Dockerfile`,
  `backend/.dockerignore`) and builds a container image directly from the
  connected GitHub repo. No local Docker or `gcloud` install is required by
  anyone deploying this project — the build happens entirely in Google's
  cloud.
- **Start command:** baked into `backend/Dockerfile`'s `CMD` —
  `uvicorn main:app --host 0.0.0.0 --port $PORT`, reading Cloud Run's
  injected `$PORT` dynamically (never hardcoded).
- **Environment configuration:** the same 3 secrets
  (`GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`) plus
  `CORS_ALLOWED_ORIGIN`, set via Cloud Run's console environment-variable
  UI, never committed to the repository (ADR-15's pattern is unchanged,
  only the dashboard it's entered into).
- **Cold start:** with `min-instances=0` (recommended, see below), the
  service scales to zero when idle and pays a cold-start penalty on the
  next request — the same category of behavior Render's free tier already
  had, so the frontend's existing "waking up" UX handling
  (`docs/UI_UX.md`) applies unchanged.

**Why this provider:** ADR-19 — genuinely free tier with configurable
memory well beyond the 512MB that broke on Render, evidenced by live
testing rather than assumed; no card required; same Dockerfile-based image
is portable to any other OCI-compatible host if ever needed.

### Step-by-step: deploying the backend to Cloud Run

This section is written for the project owner to execute directly in the
GCP Console — no step here involves Claude/an agent creating an account or
entering a secret; those actions are explicitly out of scope for any
automated agent on this project. Google's Console UI wording shifts over
time, so if an exact label below doesn't match what you see, look for the
control matching the described concept rather than the literal string.

1. **Create (or select) a GCP project.** At
   [console.cloud.google.com](https://console.cloud.google.com), create a
   new project (or reuse an existing one) from the project picker at the
   top of the page. No billing account/payment method needs to be attached
   to use Cloud Run's and Cloud Build's free tiers — if the Console ever
   prompts you to attach one to proceed, stop and re-check whether the
   action you're taking is actually still within the free tier before
   continuing.
2. **Enable the required APIs.** In the Console's search bar, find and
   enable: **Cloud Run API** and **Cloud Build API** (Cloud Build runs
   automatically as part of Cloud Run's "deploy from repository" flow, but
   the API must be enabled once per project — the Console will often
   offer to enable it automatically the first time you need it, which is
   fine to accept).
3. **Start a new Cloud Run service.** From the Cloud Run section of the
   Console, choose to create a new service, then select the option to
   deploy continuously from a source repository (as opposed to deploying a
   pre-built container image from a registry).
4. **Connect the GitHub repository.** Authorize Cloud Build's GitHub
   connection (a one-time OAuth-style authorization to your GitHub
   account) and select the repository `ameyg23/RAG_Project`. Choose the
   branch to deploy from (typically `main`).
5. **Set the build context / source location to `backend/` — this is the
   step most likely to be gotten wrong in this repo's monorepo layout.**
   Cloud Run's source-deploy configuration has a field for the directory
   Cloud Build should treat as the build root (worded along the lines of
   "source location," "build context directory," or shown as a path
   filter/subdirectory field). Set it to `backend` — **not** the repo
   root — since `backend/Dockerfile` and `backend/requirements.txt` live
   inside that subdirectory, exactly mirroring `render.yaml`'s
   `rootDir: backend` setting for the old Render deploy. If this is left
   at the repo root, the build will fail to find `Dockerfile` (or, if a
   `Dockerfile` autodetect field is separately configurable, be sure that
   path is set to `backend/Dockerfile` as well, consistent with the same
   subdirectory).
6. **Confirm Cloud Build detects the Dockerfile.** With the build context
   set correctly, Cloud Run/Cloud Build should auto-detect
   `backend/Dockerfile` as the build strategy (rather than falling back to
   Google's generic Buildpacks auto-detection for a bare Python app) — the
   Console typically shows which build strategy it picked before you
   confirm the deploy; verify it says "Dockerfile," not "Buildpacks."
7. **Set memory and CPU allocation.** Configure the service's container
   resources to **1 GiB memory / 1 vCPU**. Reasoning: this project's
   measured failure point was 512MB under real embedding-model inference
   load (ADR-19); 1 GiB gives roughly 2x that ceiling as real margin —
   enough headroom for the embedding model, FastAPI/uvicorn, and both the
   Groq and Qdrant clients to coexist comfortably, without over-allocating
   into a range that would burn through the free monthly compute-second
   allowance meaningfully faster for a low-traffic portfolio demo. 1 vCPU
   is the standard default pairing and is not the constrained resource
   here — this workload is memory-bound, not CPU-bound (evidenced by
   `OMP_NUM_THREADS=1`/`MKL_NUM_THREADS=1`/`OPENBLAS_NUM_THREADS=1` already
   capping thread-pool usage in `backend/Dockerfile`).
8. **Set scaling to `min-instances=0`.** This keeps the service
   scale-to-zero (recommended) so idle time costs nothing against the free
   compute-second allowance, at the cost of a cold start on the first
   request after an idle period — the same tradeoff Render's free tier
   already had, and one the frontend already has UX handling for
   (`docs/UI_UX.md`'s "waking up" state). Do **not** set `min-instances=1`
   unless you have deliberately decided to accept continuous billing
   outside the free tier in exchange for eliminating cold starts —
   documented here as an explicit tradeoff, not a default.
9. **Set the required environment variables**, entered directly into Cloud
   Run's environment-variables configuration section (you type these in
   yourself — no agent working on this project ever sees or handles the
   actual values):
   - `GROQ_API_KEY` — your Groq API key.
   - `QDRANT_URL` — your Qdrant Cloud cluster endpoint.
   - `QDRANT_API_KEY` — your Qdrant Cloud API key.
   - `CORS_ALLOWED_ORIGIN` — set to `http://localhost:5173` for now (same
     two-phase pattern used for Render: this gets updated to the real
     Cloudflare Pages URL once the frontend is deployed, see step 6 of the
     Deployment Sequence below).
10. **Allow unauthenticated invocations.** Since this is a public-facing
    API with no separate auth layer of its own, set the service's ingress/
    authentication setting to allow public (unauthenticated) access —
    otherwise the frontend cannot reach it at all.
11. **Deploy.** Confirm the deploy; Cloud Build will build the image from
    `backend/Dockerfile` and Cloud Run will start the service. First builds
    typically take a few minutes (installing `torch` and
    `sentence-transformers` is the bulk of the build time).
12. **Find the deployed service's URL.** Once the deploy finishes, Cloud
    Run's service detail page shows a public HTTPS URL (a
    `*.run.app` domain, e.g. `https://rag-chatbot-backend-xxxxx.run.app`).
    This is the URL to verify `GET /health` against, and the value the
    frontend's `VITE_API_BASE_URL` must later be set to (see
    `docs/ENVIRONMENT.md`).
13. **Verify.** Visit `<service-url>/health` in a browser or via `curl` and
    confirm a `200` response with `"status": "ok"`. Then exercise a real
    `POST /chat` request (e.g. via the not-yet-repointed frontend running
    locally against this URL, or a manual request) to confirm the specific
    failure mode that motivated this migration (embedding-model memory
    load under real chat traffic) is actually resolved — don't just trust
    the health check, per this project's established practice of verifying
    real infrastructure behavior rather than assuming it (ADR-07/ADR-08's
    own lesson, reaffirmed by ADR-19 itself).

**Redeploying after an environment-variable change:** Cloud Run redeploys
automatically when you save a new revision with updated environment
variables (each save creates a new revision); no separate manual redeploy
step is needed, similar to Render's behavior.

**Monitoring free-tier usage:** Cloud Run's Console shows request count and
compute-second usage per service under its Metrics tab — check this
periodically (same spirit as monitoring Render's instance-hours or Qdrant's
suspension window) if traffic ever grows beyond light portfolio-demo
levels.

## Vector Storage — Qdrant Cloud (Free Tier)

- **Free tier:** one cluster, 0.5 vCPU / 1GB RAM / 4GB disk — comfortably
  enough for this project's 384-dim vectors at small scale (the free tier
  supports roughly 1M vectors at 768-dim; this project uses fewer
  dimensions and a much smaller corpus). No credit card required;
  permanently free, not a trial.
- **Persistence:** genuinely persists independent of the backend's restart/
  redeploy cycle — this is *why* Qdrant Cloud was chosen over a
  self-hosted Chroma/FAISS file on the backend's own ephemeral disk
  (ADR-07) — true whether that backend is Render or, currently, Cloud Run,
  both of which have non-persistent container filesystems.
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

- **Provider / model:** Groq, `qwen/qwen3.8-27b` (see ADR-08 — the
  originally-planned `llama-3.3-70b-versatile` had been removed from Groq's
  catalog by the time this was checked against the real API during Phase 10
  implementation; the actually-available model list was confirmed live via
  `client.models.list()`, not assumed).
- **Free limits (as verified 2026-09):** no credit card required; roughly
  30 requests/minute and 14,400 requests/day at the organization level,
  with tighter model-specific daily/token caps for larger models. **These
  numbers drift — re-verify at
  [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits)
  before relying on them for a real launch**, rather than treating today's
  figures as permanently fixed. **The model catalog drifts too** — this
  project's own history is proof (see ADR-08); re-run
  `client.models.list()` before any redeploy rather than trusting a
  hardcoded model name indefinitely.
- **Rate-limit / quota behavior:** exceeding limits returns HTTP 429 from
  Groq, which the backend maps to the sanitized `502 LLM_UNAVAILABLE`
  response defined in `docs/API.md` — never a raw provider error.

**Why this provider:** ADR-08 — no card required, fast inference, and
per-minute limits better suited to interactive chat than the stricter daily
caps observed on comparable free-tier Gemini models during this project's
provider research.

## Cross-Cutting Concerns

**Cold starts:** only the backend cold-starts (Render previously, Cloud Run
now with `min-instances=0`); Cloudflare Pages is always-on static hosting
with no equivalent delay. UI mitigation is owned by `docs/UI_UX.md`
(distinct "waking up" messaging), which was built for Render's cold start
and applies unchanged to Cloud Run's (same category of behavior, ADR-19).

**Persistence risks:** the Qdrant 7-day/28-day inactivity suspension
(above) is the single biggest "this looks broken but isn't" risk in this
architecture. Mitigation is documentation + a one-command reseed script,
deliberately not an automated keep-alive. This is entirely independent of
the backend hosting choice (Render or Cloud Run) — Qdrant Cloud is
unaffected by ADR-19.

**CORS:** the backend's allowed origin (`CORS_ALLOWED_ORIGIN`, see
`docs/ENVIRONMENT.md`) must be updated to match whichever Cloudflare Pages
URL (or custom domain) is actually assigned — a manual one-line config step
performed once, immediately after the first frontend deploy.

**Environment variables:** full list in `docs/ENVIRONMENT.md`.

**Secret management:** every secret lives only in (a) the issuing
provider's own dashboard (where the key value is generated — Groq, Qdrant),
and (b) Cloud Run's environment-variable console (or Render's, if using
the paid-tier fallback). Nothing secret is ever committed to git or present
in the Cloudflare Pages build output.

## Deployment Sequence

1. Create a Qdrant Cloud free cluster; record its URL and API key.
2. Create a Groq account and generate an API key (no card required).
3. Deploy the backend to Cloud Run (see the step-by-step guide above); set
   `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, and `CORS_ALLOWED_ORIGIN`
   as environment variables; verify `GET /health` returns `"status": "ok"`
   from the Cloud Run service's public URL.
4. Run `backend/scripts/seed_demo_kb.py` once, locally, against the live
   Qdrant cluster (it talks to Qdrant directly, not through the deployed
   backend — see the script's own docstring) to populate the demo
   knowledge base.
5. Deploy the frontend to Cloudflare Pages with `VITE_API_BASE_URL` set to
   the deployed Cloud Run service's `*.run.app` URL.
6. Update the backend's `CORS_ALLOWED_ORIGIN` environment variable (in
   Cloud Run's console) to the final Cloudflare Pages URL and let Cloud Run
   redeploy the new revision.

## How to Replace an API Key

Rotate the key in the issuing provider's dashboard (Groq or Qdrant), then
update the corresponding environment variable in Cloud Run's console
(saving triggers a new revision automatically — no separate manual redeploy
step). **No code change is required anywhere** — this follows directly
from ADR-15's backend-only secret pattern, which is provider-agnostic.

## How to Avoid Accidental Billing

Never add a payment method to any of the four services used here (Google
Cloud [Cloud Run/Cloud Build], Groq, Qdrant Cloud, Cloudflare Pages) for
this project — every free tier referenced above explicitly requires no
card. If any provider ever prompts for card entry to continue using a
feature this plan relies on, treat that as a signal to stop and
re-evaluate the plan, not to proceed. (Render remains a legitimate fallback
option specifically *if* the user decides to pay — see the Render section
above — but that is an explicit, deliberate choice, not something to be
led into unintentionally.)

## Acceptance Criteria Check

- **Every external service has a documented cost model:** ✓ (Cloudflare
  Pages, Google Cloud Run, Qdrant Cloud, Groq — each above; Render kept as
  a documented paid-tier fallback).
- **Persistence is explicitly addressed:** ✓ (Qdrant persistence + its
  suspension risk; ephemeral backend container filesystem; transient raw
  files).
- **No paid service is required for V1:** ✓ — all four current services
  (Cloudflare Pages, Cloud Run, Qdrant Cloud, Groq) are used at their
  no-card free tier.
- **API keys are not exposed:** ✓ — backend-only environment variables
  (ADR-15), never in frontend build output.
- **Deployment can be reproduced from the documentation:** ✓ — the ordered
  six-step sequence above, plus the detailed Cloud Run step-by-step guide,
  is sufficient to redeploy from scratch.
