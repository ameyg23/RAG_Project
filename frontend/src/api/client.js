// Typed API client matching docs/API.md exactly, field-for-field.
// One function per backend endpoint. All requests go through the FastAPI
// backend only — no LLM/vector-DB key ever lives here (ADR-15).

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const SESSION_TOKEN_STORAGE_KEY = 'rag_session_token'

function getStoredSessionToken() {
  try {
    return localStorage.getItem(SESSION_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setStoredSessionToken(token) {
  try {
    if (token) localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, token)
  } catch {
    // localStorage unavailable (private mode, disabled storage) — session
    // token simply won't persist across reloads; not a fatal error.
  }
}

class ApiError extends Error {
  constructor(code, message, status) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
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

export function sendChatMessage(knowledgeBaseId, message) {
  return request('/chat', {
    method: 'POST',
    body: { knowledge_base_id: knowledgeBaseId, message },
  })
}

export { ApiError }
