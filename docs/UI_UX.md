# UI/UX Specification

Companion to `ARCHITECTURE.md` §2 (frontend architecture) and `docs/API.md`
(the responses these screens render). For every screen/state below:
what the user sees, available actions, disabled actions, loading behavior,
error behavior.

## 1. Landing Page

**Sees:** a one-line explanation of the product ("Ask questions about a demo
document set, or upload your own and chat with it — every answer is backed
by a source citation"), the demo knowledge base already selected and active,
3–5 suggested questions, an empty chat thread, and a visible "Upload your
own documents" entry point.

**Available actions:** click a suggested question, type a free-form
question, switch to "Your documents" via the KB selector, open the upload
interface.

**Disabled actions:** none — the demo KB is always ready.

**Loading behavior:** if the backend is cold (Render free tier, ADR-10),
the first `/health` call may take 30–60s; the landing page shows a subtle
"Connecting…" indicator rather than appearing broken, and enables the chat
input as soon as `/health` resolves.

**Error behavior:** if `/health` never resolves (backend fully down), show
a calm banner: "The demo is temporarily unavailable. Please try again in a
minute." with a manual retry button — never a blank/broken page.

## 2. Demo Knowledge-Base View

**Sees:** a "Demo" badge (fixed color/icon, consistently used everywhere the
demo KB is referenced), a read-only list of the demo's documents (name only,
no size/status — they are always `READY`), no upload control, no delete
control.

**Available actions:** view document names, ask questions.

**Disabled actions:** upload, delete — these controls are not merely
disabled, they are **not rendered at all** for the demo KB (FR-004), so
there is nothing to click and no ambiguity about read-only status.

**Loading behavior:** document list loads once per KB selection; cached
thereafter for the session.

**Error behavior:** if the document list fails to load, show an inline
retry affordance scoped to that panel only (chat remains usable).

## 3. User Documents View

**Sees:** a "Your documents" badge, a list of the session's own uploaded
documents each with a status badge (`UPLOADED`/`PROCESSING`/`READY`/
`FAILED`), size, and upload time.

**Available actions:** upload more (up to the per-request cap), delete any
document, ask questions (if ≥1 document is `READY`).

**Disabled actions:** delete is available even on `PROCESSING` documents
(canceling isn't a separate concept — deleting a still-processing document
simply removes it once processing settles, or marks it for removal — see
`docs/DOCUMENT_PROCESSING.md`).

**Loading behavior:** list re-polls at a fixed interval while any document
is `UPLOADED`/`PROCESSING`, stops polling once all documents reach a
terminal state (`READY`/`FAILED`).

**Error behavior:** a failed status poll retries silently in the background
(not surfaced as a user-facing error unless persistent — see Error State
§13).

## 4. Upload Interface

**Sees:** a drag-and-drop zone plus a file-picker button, live counters
("3 of 5 files selected"), and per-file size shown before submission.

**Available actions:** select up to 5 files, remove a selected file before
submitting, submit.

**Disabled actions:** the submit button is disabled if 0 files are
selected, more than 5 are selected, any selected file exceeds 5MB, or any
selected file's type isn't pdf/docx/txt/md — each violation shown inline
next to the offending file, before any network request is made.

**Loading behavior:** client-side validation is instant; this is explicitly
labeled to the user as a convenience check — the interface states "Files are
re-checked on upload" so a user never assumes client validation is the only
gate (server re-validates identically per `docs/API.md`).

**Error behavior:** if the server rejects the batch despite passing client
checks (e.g. a race with a slightly stale client-side rule), the exact
server error message (from `docs/API.md`'s `400` responses) is shown,
naming the offending file.

## 5. Processing State

**Sees:** each just-uploaded file shows a spinner/progress badge labeled
"Processing…", with a soft expectation set in copy ("Usually ready within
a few seconds to a minute").

**Available actions:** continue using the app (switch KBs, chat against
already-`READY` documents) while processing continues in the background —
processing never blocks the rest of the UI.

**Disabled actions:** none beyond §3's per-document rules.

**Loading behavior:** status polling (`GET /documents/{id}/status`) at a
fixed short interval (e.g. every 2 seconds) per in-flight document, stopping
once each reaches `READY`/`FAILED`.

**Error behavior:** n/a at this stage — outcomes are covered by §6/§7.

## 6. Ready State

**Sees:** status badge changes to "Ready" (e.g. green check), chunk count
optionally shown as a subtle detail.

**Available actions:** chat input for this KB becomes enabled (if it was
disabled due to zero ready documents before).

**Disabled actions:** none.

**Loading behavior:** none — terminal state.

**Error behavior:** n/a.

## 7. Failed State

**Sees:** status badge shows "Failed", with the exact `failure_reason`
string from `docs/DOCUMENT_PROCESSING.md` shown in plain language (e.g.
"No extractable text found — this file may be a scanned image.").

**Available actions:** re-upload the same file as a new upload (there is no
"retry" button that resubmits the same `document_id` — re-upload always
creates a new one, consistent with the no-auto-retry decision).

**Disabled actions:** the failed document cannot be queried; it does not
block other documents in the same original batch, which continue
processing/showing their own independent status.

**Loading behavior:** none — terminal state.

**Error behavior:** this *is* the error display; no further error state
layered on top.

## 8. Knowledge-Base Selector

**Sees:** a two-option toggle ("Demo" / "Your documents"), each with a
distinct, consistent badge color/icon used everywhere that KB is referenced
in the UI (chat thread header, document list, citations) so the active KB
is never ambiguous.

**Available actions:** switch between the two.

**Disabled actions:** "Your documents" is shown but visually marked "Empty —
upload to get started" if the session has no documents yet, rather than
being hidden (so the option to create one is always discoverable).

**Loading behavior:** switching is instant (both KBs' document lists are
prefetched/cached once loaded).

**Error behavior:** none specific — switching itself cannot fail.

**Side effect:** switching clears the currently displayed chat thread
(FR-032) — this is communicated with a brief inline note ("Starting a new
conversation for this knowledge base") so it doesn't read as data loss.

## 9. Suggested Questions

**Sees (Demo KB):** 3–5 fixed, curated example questions rendered as
clickable chips above the chat input, each guaranteed answerable from demo
content (curated once the demo content is finalized — see
`docs/RAG_EVALUATION.md` dataset dependency).

**Sees (User KB, empty):** no suggested questions (none would be answerable
yet); instead a single call-to-action: "Upload a document to start asking
questions."

**Sees (User KB, ≥1 ready document):** no fixed suggestions (content is
unknown/arbitrary), instead a generic placeholder prompt in the chat input,
e.g. "Ask something about your uploaded documents…".

**Available actions:** click a suggestion to instantly populate and submit
it as a chat message.

**Disabled actions:** n/a.

## 10. Chat Interface

**Sees:** a scrollable message thread (user messages right-aligned,
assistant messages left-aligned with attached sources), a text input, a
send button.

**Available actions:** type and send a message, click a suggested question,
scroll history, click a citation to expand it.

**Disabled actions:** input is disabled with an inline explanatory message
when the active KB has zero `READY` documents (FR-056): "This knowledge
base has no ready documents yet."

**Loading behavior — two distinct states:**
- **Normal per-message loading:** a lightweight "Thinking…" indicator while
  waiting for `/chat` to resolve under normal (warm-backend) conditions.
- **Cold-start loading (NFR-003):** if the backend was asleep (first
  request after Render's 15-minute idle spin-down), the UI shows a visibly
  different message — "Waking up the server, this can take up to a
  minute…" — so a 30–60s wait reads as expected behavior, not a hang. This
  is inferred client-side by starting a longer-format loading state if no
  response arrives within ~5 seconds of a request being sent.

**Error behavior:** see §13.

## 11. Source Citations

**Sees:** each assistant message with a non-empty `sources[]` shows a
citation list (inline numbered markers matching the answer text, or an
expandable "Sources (2)" section) — each entry shows document name, locator
("page 8" / "chunk 3"), and a short snippet.

**Available actions:** expand/collapse the source list, hover/click a
citation marker to jump to its source entry.

**Disabled actions:** n/a.

**Special case — removed source (FR-042):** if `is_removed: true` on a
citation, the entry renders with a muted style and a label "Original
document has been removed" instead of a broken link or missing data —
never crashes and never silently disappears (the citation itself is still
historically accurate for that past answer).

## 12. Empty State

**Sees (fresh "Your documents" KB, zero uploads):** the document list area
shows a friendly empty-state illustration/message ("No documents yet") with
a prominent upload call-to-action; chat input disabled per §10's rule.

**Available actions:** open the upload interface.

**Disabled actions:** chat input.

## 13. Error State

Every backend error (`docs/API.md`) maps to a distinct, plain-language,
non-technical message, always paired with a retry action except where noted:

| API error | User-facing message | Retryable? |
|---|---|---|
| `400` upload validation (FILE_TOO_LARGE / UNSUPPORTED_FILE_TYPE / TOO_MANY_FILES) | Exact validation message, inline near the offending file | Yes — fix selection and resubmit |
| `403` forbidden (session mismatch) | "You don't have access to this knowledge base." | No retry — offer a button to switch back to the Demo KB |
| `404` not found | "That knowledge base or document no longer exists." | Offer to refresh the KB list |
| `502` LLM/vector-DB unavailable | "The answer service is temporarily unavailable. Please try again shortly." | Yes — visible "Try again" button |
| `503` empty KB | "This knowledge base has no ready documents yet." | N/A — same as §10's disabled-input state, not a transient error |
| Network/timeout (no response) | "Couldn't reach the server. Check your connection and try again." | Yes |

No raw exception text, stack trace, or provider (Groq/Qdrant) error payload
is ever shown to the user — this mirrors the sanitized error contract in
`docs/API.md`/`docs/SECURITY.md`.

## Acceptance Criteria Check

- **A first-time visitor knows what the application does:** landing page
  one-liner (§1) states the product's purpose before any interaction.
- **A first-time visitor knows what questions can be asked:** suggested
  questions on the demo KB (§9) are visible immediately, with no upload
  required.
- **A user can understand document status:** explicit status badges and
  plain-language failure reasons (§5–7) at every stage of
  `docs/DOCUMENT_PROCESSING.md`'s state machine.
- **A user can distinguish demo documents from their documents:** a
  consistent, always-visible KB badge (§2, §3, §8) rather than a
  one-time-only indicator.
- **A user can identify the source of an answer:** every grounded answer
  carries an inline citation with document name and locator (§11), and the
  no-context path (FR-022) never presents an uncited answer.
