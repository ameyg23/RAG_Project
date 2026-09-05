import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, listDocuments, sendChatMessage } from '../api/client'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

const COLD_START_DELAY_MS = 5000

// The demo composer is pre-filled with this exact meta-question rather than
// one of the real curated questions — sending it (unedited) never calls the
// real chat API at all; it's answered entirely client-side with the actual
// ingested document names + the real suggested questions, so a first-time
// visitor gets oriented before spending a real LLM call on content they
// haven't chosen yet. Editing the box to ask anything else always goes
// through the real pipeline as normal.
export const META_PROMPT = 'What can I ask about this knowledge base?'

// Client-side-only response to the meta-question — lists the real ingested
// document names plus the real curated suggested questions. Never touches
// sendChatMessage()/the real LLM.
async function buildMetaResponse(knowledgeBaseId, suggestions) {
  let documentNames = []
  try {
    const result = await listDocuments(knowledgeBaseId)
    documentNames = (result.documents ?? []).map((doc) => doc.filename)
  } catch {
    // Non-fatal — the meta-response still lists the suggested questions
    // even if the document list itself couldn't be fetched.
  }

  const lines = []
  if (documentNames.length > 0) {
    lines.push(`This knowledge base includes: ${documentNames.join(', ')}.`, '')
  }
  if (suggestions.length > 0) {
    lines.push('You can ask things like:')
    suggestions.forEach((q) => lines.push(`• ${q}`))
  } else {
    lines.push('Try asking a question about the documents listed above.')
  }
  return lines.join('\n')
}

// Server-provided messages are already safe, user-facing text (docs/API.md) —
// trust them directly. 503 is the disabled-input state (FR-056), not a
// transient error, so it's never surfaced here as a retryable chat error
// (docs/UI_UX.md §13's own note) — it's structurally unreachable anyway,
// since the input is disabled before a message can be sent in that state.
function errorDisplay(err) {
  if (err instanceof ApiError) {
    const retryable = err.status === 502 || err.status === 0
    return { message: err.message, retryable }
  }
  return {
    message: "Couldn't reach the server. Check your connection and try again.",
    retryable: true,
  }
}

export default function ChatPanel() {
  const { activeKnowledgeBaseId, chatMessages, setChatMessages, knowledgeBases } = useSession()

  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isColdStart, setIsColdStart] = useState(false)
  const [error, setError] = useState(null)
  const [hasReadyUserDocs, setHasReadyUserDocs] = useState(false)
  const coldStartTimerRef = useRef(null)
  const hasPrefilledRef = useRef(false)

  const isDemo = activeKnowledgeBaseId === DEMO_KB_ID
  const activeKb = knowledgeBases.find((kb) => kb.knowledge_base_id === activeKnowledgeBaseId)
  // Memoized so the effect below (keyed on this array) doesn't see a new []
  // reference on every render when there's nothing to show yet.
  const suggestedQuestions = useMemo(
    () => (isDemo ? (activeKb?.suggested_questions ?? []) : []),
    [isDemo, activeKb?.suggested_questions]
  )
  const userDocumentCount = activeKb?.document_count ?? 0

  // Landing on the demo KB with an empty thread pre-fills the composer with
  // META_PROMPT (a real, sendable value, not just a placeholder hint) so a
  // first-time visitor can just hit Send and get oriented. Only ever does
  // this once per KB visit — switching away and back re-arms it, but it
  // never overwrites anything the visitor typed themselves or sent.
  useEffect(() => {
    hasPrefilledRef.current = false
    setInput('')
  }, [activeKnowledgeBaseId])

  useEffect(() => {
    if (isDemo && !hasPrefilledRef.current && chatMessages.length === 0) {
      hasPrefilledRef.current = true
      setInput(META_PROMPT)
    }
  }, [isDemo, chatMessages.length])

  // Demo KB is always ready to chat (pre-seeded, FR-002) — the known backend
  // gap that reports document_count: 0 for it is irrelevant here, since
  // readiness for the demo KB is never gated on that field at all. For the
  // user KB, document_count alone can't distinguish READY from
  // FAILED/PROCESSING, so per-document status (GET .../documents) is the
  // authoritative signal.
  useEffect(() => {
    if (isDemo || !activeKnowledgeBaseId) {
      setHasReadyUserDocs(false)
      return
    }
    let cancelled = false
    listDocuments(activeKnowledgeBaseId)
      .then((result) => {
        if (!cancelled) {
          setHasReadyUserDocs((result.documents ?? []).some((d) => d.status === 'READY'))
        }
      })
      .catch(() => {
        if (!cancelled) setHasReadyUserDocs(false)
      })
    return () => {
      cancelled = true
    }
  }, [isDemo, activeKnowledgeBaseId, userDocumentCount])

  useEffect(() => () => clearTimeout(coldStartTimerRef.current), [])

  const isReady = isDemo || hasReadyUserDocs

  async function sendMessage(message) {
    const trimmed = message.trim()
    if (!trimmed || !isReady || isSending) return

    setError(null)
    setChatMessages((prev) => [...prev, { role: 'user', content: trimmed }])
    setInput('')
    setIsSending(true)

    // The meta-question is answered entirely client-side — never spends a
    // real LLM call on a question that has no content-based answer.
    if (isDemo && trimmed === META_PROMPT) {
      const content = await buildMetaResponse(activeKnowledgeBaseId, suggestedQuestions)
      setChatMessages((prev) => [...prev, { role: 'assistant', content, sources: [] }])
      setIsSending(false)
      return
    }

    setIsColdStart(false)
    coldStartTimerRef.current = setTimeout(() => setIsColdStart(true), COLD_START_DELAY_MS)

    try {
      const result = await sendChatMessage(activeKnowledgeBaseId, trimmed)
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: result.answer, sources: result.sources ?? [] },
      ])
    } catch (err) {
      setError(errorDisplay(err))
    } finally {
      clearTimeout(coldStartTimerRef.current)
      setIsSending(false)
      setIsColdStart(false)
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    sendMessage(input)
  }

  function handleRetry() {
    const lastUser = [...chatMessages].reverse().find((m) => m.role === 'user')
    if (lastUser) sendMessage(lastUser.content)
  }

  const placeholder = !isReady
    ? 'This knowledge base has no ready documents yet.'
    : isDemo
      ? 'Ask a question about the demo knowledge base…'
      : 'Ask something about your uploaded documents…'

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__thread">
        {chatMessages.length === 0 && isReady && (
          <p className="chat-panel__empty">
            {isDemo
              ? 'A sample question is ready in the box below — hit Send, or type your own.'
              : 'Ask something about your uploaded documents.'}
          </p>
        )}
        {chatMessages.length === 0 && !isReady && userDocumentCount === 0 && (
          <p className="chat-panel__empty">Upload a document to start asking questions.</p>
        )}
        {chatMessages.length === 0 && !isReady && userDocumentCount > 0 && (
          <p className="chat-panel__empty">
            Ask a question once this knowledge base has ready documents.
          </p>
        )}

        {chatMessages.map((message, index) => (
          <div key={index} className={`chat-message chat-message--${message.role}`}>
            <p className="chat-message__content">{message.content}</p>
            {message.role === 'assistant' && message.sources?.length > 0 && (
              <ul className="chat-message__sources">
                {/* One row per distinct document, name only — a single answer
                    can cite several chunks from the same file, but the
                    source list should name each document once, not repeat
                    it or show its full chunk text. */}
                {Array.from(
                  new Map(message.sources.map((source) => [source.document_id, source])).values()
                ).map((source) => (
                  <li
                    key={source.document_id}
                    className={`chat-source${source.is_removed ? ' chat-source--removed' : ''}`}
                  >
                    <span className="chat-source__name">{source.document_name}</span>
                    {source.is_removed && (
                      <span className="chat-source__removed-note"> (document removed)</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}

        {isSending && (
          <p className="chat-panel__status" role="status">
            {isColdStart ? 'Waking up the server, this can take up to a minute…' : 'Thinking…'}
          </p>
        )}

        {error && (
          <p className="chat-panel__error" role="alert">
            {error.message}
            {error.retryable && (
              <button type="button" className="chat-panel__retry" onClick={handleRetry}>
                Try again
              </button>
            )}
          </p>
        )}
      </div>

      {isReady && isDemo && suggestedQuestions.length > 0 && chatMessages.length > 0 && (
        <div className="chat-panel__suggestions">
          <p className="chat-panel__suggestions-label">You can also ask:</p>
          {suggestedQuestions.map((question) => (
            <button
              key={question}
              type="button"
              className="chat-suggestion-chip"
              onClick={() => sendMessage(question)}
              disabled={isSending}
            >
              {question}
            </button>
          ))}
        </div>
      )}

      <form className="chat-panel__composer" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={placeholder}
          disabled={!isReady || isSending}
          aria-disabled={!isReady || isSending}
          autoComplete="off"
          name="chat-message"
        />
        <button type="submit" disabled={!isReady || isSending || !input.trim()}>
          Send
        </button>
      </form>
    </section>
  )
}
