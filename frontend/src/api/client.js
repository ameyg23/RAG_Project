// Typed API client matching docs/API.md exactly, field-for-field.
// One function per backend endpoint. All requests go through the FastAPI
// backend only — no LLM/vector-DB key ever lives here (ADR-15).

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// In-memory only, on purpose: the session token (and therefore "Your
// Documents") must NOT survive a page refresh or reopen (product decision —
// see SessionContext.jsx). This module-level variable is how SessionContext
// hands the current token to `request()` below without any React prop
// drilling; it is never written to localStorage/sessionStorage, so it
// resets to null on every reload, same as SessionContext's own state.
let currentSessionToken = null

function getStoredSessionToken() {
  return currentSessionToken
}

export function setStoredSessionToken(token) {
  currentSessionToken = token
}

class ApiError extends Error {
  // `retryable` (ADR-18): optional 4th arg, defaults to `undefined` so every
  // pre-existing call site (which never passes it) leaves `err.retryable`
  // undefined and `errorDisplay()`'s `??` falls through to its original
  // status-based inference — zero behavior change for any already-tested
  // error path. Only the new streamed `POST /chat` ERROR events pass this
  // explicitly, carried verbatim from the wire event's own `retryable` field
  // instead of being inferred from an HTTP status that no longer exists once
  // the 200 response has started streaming.
  constructor(code, message, status, retryable) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
  }
}

async function request(path, { method = 'GET', headers = {}, body, isMultipart = false } = {}) {
  const sessionToken = getStoredSessionToken()
  const finalHeaders = { ...headers }
  if (sessionToken) finalHeaders['X-Session-Token'] = sessionToken
  if (!isMultipart && body !== undefined) {
    finalHeaders['Content-Type'] = 'application/json'
  }

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: finalHeaders,
      body: isMultipart ? body : body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(
      'NETWORK_ERROR',
      "Couldn't reach the server. Check your connection and try again.",
      0
    )
  }

  let data = null
  try {
    data = await response.json()
  } catch {
    // Non-JSON or empty body — fall through with data=null.
  }

  if (!response.ok) {
    const errorDetail = data?.error
    throw new ApiError(
      errorDetail?.code ?? 'UNKNOWN_ERROR',
      errorDetail?.message ?? 'Something went wrong. Please try again.',
      response.status
    )
  }

  return data
}

export function getHealth() {
  return request('/health')
}

export function listKnowledgeBases() {
  return request('/knowledge-bases')
}

export function listDocuments(knowledgeBaseId) {
  return request(`/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents`)
}

export function uploadDocuments(files) {
  const formData = new FormData()
  for (const file of files) formData.append('files', file)
  return request('/documents/upload', { method: 'POST', body: formData, isMultipart: true })
}

export function getDocumentStatus(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}/status`)
}

export function deleteDocument(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
}

// `conversationHistory` (ADR-16): recent prior turns of this same thread,
// each `{ role: 'user' | 'assistant', content: string }` — see docs/API.md's
// `POST /chat` section. The caller (ChatPanel) is responsible for slicing to
// the last 3 exchanges and stripping any non-contract fields (e.g.
// `sources`); this function forwards it as-is under `conversation_history`.
// Omitted/empty history is sent as no field at all, matching the documented
// "first message of a thread" shape exactly (skips Stage 6.5 server-side).
//
// ADR-18: `POST /chat` now streams chunked NDJSON — one `{"stage": ...}`
// object per line, ending in a terminal `COMPLETED` or `ERROR` event. This
// function reads the stream incrementally (never buffering the whole body
// before acting) and invokes `onStage(stage)` for each intermediate stage
// event as it arrives, then resolves with exactly the same `{answer,
// sources}` shape callers received before this ADR, or rejects with an
// `ApiError` carrying the wire event's own `code`/`message`/`retryable`.
//
// `options.signal` (an `AbortSignal`) is passed straight through to `fetch`
// so an in-flight request can be cancelled cleanly (ChatPanel.jsx's
// concurrency guard, ADR-18).
export async function sendChatMessage(
  knowledgeBaseId,
  message,
  conversationHistory = [],
  { onStage, signal } = {}
) {
  const body = { knowledge_base_id: knowledgeBaseId, message }
  if (conversationHistory.length > 0) {
    body.conversation_history = conversationHistory
  }

  const sessionToken = getStoredSessionToken()
  const headers = { 'Content-Type': 'application/json' }
  if (sessionToken) headers['X-Session-Token'] = sessionToken

  let response
  try {
    response = await fetch(`${BASE_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    // Preserve AbortError's identity (name/instanceof DOMException) so a
    // deliberate cancellation is distinguishable from a genuine network
    // failure by the caller — re-throwing it as-is, not wrapping it.
    if (err?.name === 'AbortError') throw err
    throw new ApiError(
      'NETWORK_ERROR',
      "Couldn't reach the server. Check your connection and try again.",
      0
    )
  }

  // Pre-stream failures (400/403/404/503, docs/API.md) are still a plain
  // JSON error body with a real HTTP status — identical to before ADR-18,
  // since the stream never opens for these.
  if (!response.ok) {
    let data = null
    try {
      data = await response.json()
    } catch {
      // Non-JSON or empty body — fall through with data=null.
    }
    const errorDetail = data?.error
    throw new ApiError(
      errorDetail?.code ?? 'UNKNOWN_ERROR',
      errorDetail?.message ?? 'Something went wrong. Please try again.',
      response.status
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function handleLine(line) {
    const trimmed = line.trim()
    if (!trimmed) return null
    const event = JSON.parse(trimmed)
    if (event.stage === 'COMPLETED') {
      return { answer: event.answer, sources: event.sources ?? [] }
    }
    if (event.stage === 'ERROR') {
      throw new ApiError(event.code, event.message, 200, event.retryable)
    }
    // SEARCHING / RETRIEVING / GENERATING / VALIDATING — intermediate
    // progress only, no state change of its own beyond the callback.
    onStage?.(event.stage)
    return null
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    // The last split segment may be an incomplete line (chunk boundary cut
    // mid-object) — keep it in the buffer for the next read instead of
    // parsing a truncated JSON object.
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const result = handleLine(line)
      if (result) return result
    }
  }

  // Flush any trailing buffered content once the stream itself has ended
  // (a well-formed stream's final line is `\n`-terminated, so this is
  // normally empty, but handled defensively).
  const finalResult = handleLine(buffer)
  if (finalResult) return finalResult

  // Stream ended with no terminal COMPLETED/ERROR event — treat as an
  // unexpected server error rather than resolving with nothing.
  throw new ApiError(
    'INTERNAL_ERROR',
    'An unexpected error occurred. Please try again shortly.',
    200,
    false
  )
}

export { ApiError }
