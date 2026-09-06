import {
  ArrowRight,
  FileSearch,
  Loader2,
  MessageSquare,
  Paperclip,
  Send,
  Sparkles,
  UploadCloud,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { ApiError, sendChatMessage } from '../api/client'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'
import { useView, VIEWS } from '../context/ViewContext'

const COLD_START_DELAY_MS = 5000

// ADR-18: one compact status label per real backend pipeline stage, shown
// one at a time next to a small spinning icon. Never a list/checklist — the
// status paragraph below only ever renders the single current stage's text.
const STAGE_LABELS = {
  SEARCHING: 'Searching documents…',
  RETRIEVING: 'Retrieving relevant information…',
  GENERATING: 'Generating answer…',
  VALIDATING: 'Checking sources…',
}

// ADR-18: `err.retryable` (set explicitly on streamed ERROR events, carried
// verbatim from the backend's own taxonomy) is now the authoritative source
// of retryability when present. Every pre-existing error path (`/health`,
// `/knowledge-bases`, `/documents/*`, and `/chat`'s own pre-stream 400/403/
// 404/503 responses) never sets it, so `err.retryable` is `undefined` there
// and `??` falls through to exactly today's status-based inference — zero
// behavior change for any already-tested error path. Server-provided
// messages are already safe, user-facing text (docs/API.md) — trust them
// directly. 503 is the disabled-input state (FR-056), not a transient
// error, so it's never surfaced here as a retryable chat error
// (docs/UI_UX.md §13's own note) — it's structurally unreachable anyway,
// since the input is disabled before a message can be sent in that state.
function errorDisplay(err) {
  if (err instanceof ApiError) {
    const retryable = err.retryable ?? (err.status === 502 || err.status === 0)
    return { message: err.message, retryable }
  }
  return {
    message: "Couldn't reach the server. Check your connection and try again.",
    retryable: true,
  }
}

function WelcomeHero() {
  return (
    <div className="chat-hero">
      <h2 className="chat-hero__title">Welcome to AI Knowledge Assistant</h2>
      <p className="chat-hero__subtitle">
        Ask questions about your documents using the power of Retrieval-Augmented Generation
        (RAG). Get accurate answers with source citations.
      </p>
      <div className="chat-hero__features">
        <div className="chat-hero__feature">
          <UploadCloud size={20} aria-hidden="true" />
          <div>
            <p className="chat-hero__feature-title">Upload documents</p>
            <p className="chat-hero__feature-text">PDF, DOCX, TXT (max 5 files, 5MB each)</p>
          </div>
        </div>
        <div className="chat-hero__feature">
          <MessageSquare size={20} aria-hidden="true" />
          <div>
            <p className="chat-hero__feature-title">Ask questions</p>
            <p className="chat-hero__feature-text">Get accurate, context-aware answers</p>
          </div>
        </div>
        <div className="chat-hero__feature">
          <FileSearch size={20} aria-hidden="true" />
          <div>
            <p className="chat-hero__feature-title">See sources</p>
            <p className="chat-hero__feature-text">Every answer includes source references</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function ChatPanel() {
  const { activeKnowledgeBaseId, chatMessages, setChatMessages, knowledgeBases, userDocuments } =
    useSession()
  const { setView } = useView()

  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [isColdStart, setIsColdStart] = useState(false)
  const [currentStage, setCurrentStage] = useState(null)
  const [error, setError] = useState(null)
  const coldStartTimerRef = useRef(null)
  // ADR-18 concurrency guard: an incrementing generation counter plus the
  // in-flight request's AbortController. Every onStage/final-resolution
  // state update re-checks `requestIdRef.current === myRequestId` before
  // touching React state, so a superseded request's late-arriving events
  // can never overwrite what a newer request has already displayed.
  const requestIdRef = useRef(0)
  const abortControllerRef = useRef(null)

  const isDemo = activeKnowledgeBaseId === DEMO_KB_ID
  const activeKb = knowledgeBases.find((kb) => kb.knowledge_base_id === activeKnowledgeBaseId)
  // Memoized so the effect below (keyed on this array) doesn't see a new []
  // reference on every render when there's nothing to show yet.
  const suggestedQuestions = useMemo(
    () => (isDemo ? (activeKb?.suggested_questions ?? []) : []),
    [isDemo, activeKb?.suggested_questions]
  )
  // "Your documents" readiness/ready-file-names come from the shared
  // SessionContext document list — the same canonical array the Sidebar's
  // compact DocumentsPanel and the full DocumentsView read from — instead of
  // a fourth independent fetch of the same data.
  const readyUserDocuments = useMemo(
    () => userDocuments.filter((doc) => doc.status === 'READY'),
    [userDocuments]
  )
  const hasReadyUserDocs = readyUserDocuments.length > 0

  // Switching knowledge bases always starts the composer empty - the "What
  // can I ask?" suggestion cards on the front screen are the one place
  // example questions are shown, so the input itself never needs a
  // pre-filled question.
  useEffect(() => {
    setInput('')
  }, [activeKnowledgeBaseId])

  // Aborts any in-flight streamed request on unmount, so a stale request
  // never touches state after the component is gone (ADR-18).
  useEffect(
    () => () => {
      clearTimeout(coldStartTimerRef.current)
      abortControllerRef.current?.abort()
    },
    []
  )

  const isReady = isDemo || hasReadyUserDocs

  async function sendMessage(message) {
    const trimmed = message.trim()
    if (!trimmed || !isReady) return

    // Concurrency guard (ADR-18): cancel whatever the previous request was
    // doing and mint a fresh id/AbortController for this one. Today's
    // isSending-driven disabled composer/submit/retry/suggestion-card
    // elements already prevent a second request from starting through
    // normal UI while one is in flight — this is defense-in-depth against
    // a fast-double-click/StrictMode-style race reaching sendMessage
    // anyway, so it must behave correctly even then.
    abortControllerRef.current?.abort()
    requestIdRef.current += 1
    const myRequestId = requestIdRef.current
    const controller = new AbortController()
    abortControllerRef.current = controller

    // Snapshot conversation history BEFORE the new user message is appended
    // to `chatMessages` below (ADR-16) - the backend wants only prior turns
    // of this thread, not the message being sent right now. Last 3 exchanges
    // (<=6 entries, fewer if the thread is shorter), trimmed down to just
    // {role, content} - strips `sources` and any other UI-only fields a
    // stored message may carry, since those aren't part of the request
    // contract (docs/API.md).
    const conversationHistory = chatMessages
      .slice(-6)
      .map(({ role, content }) => ({ role, content }))

    setError(null)
    setChatMessages((prev) => [...prev, { role: 'user', content: trimmed }])
    setInput('')
    setIsSending(true)
    setCurrentStage(null)

    // Cold-start interaction (ADR-18): retargeted to clear on the FIRST
    // real stage event received (below, in onStage), not at the end of the
    // whole request as before this ADR - a Render free-tier cold start
    // blocks the TCP/HTTP connection itself, so it delays literally every
    // byte including the very first stage event, making "no stage event yet
    // after 5s" a more accurate cold-start proxy than "still sending".
    clearTimeout(coldStartTimerRef.current)
    setIsColdStart(false)
    coldStartTimerRef.current = setTimeout(() => {
      if (requestIdRef.current === myRequestId) setIsColdStart(true)
    }, COLD_START_DELAY_MS)

    try {
      const result = await sendChatMessage(activeKnowledgeBaseId, trimmed, conversationHistory, {
        signal: controller.signal,
        onStage: (stage) => {
          if (requestIdRef.current !== myRequestId) return
          clearTimeout(coldStartTimerRef.current)
          setIsColdStart(false)
          setCurrentStage(stage)
        },
      })
      if (requestIdRef.current !== myRequestId) return
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: result.answer, sources: result.sources ?? [] },
      ])
    } catch (err) {
      // A deliberately superseded/cancelled request's abort is a silent
      // no-op, never an error banner (ADR-18) - it was cancelled on
      // purpose, not genuinely failed.
      if (err?.name === 'AbortError') return
      if (requestIdRef.current !== myRequestId) return
      setError(errorDisplay(err))
    } finally {
      // Only the request that is still "current" gets to clear the
      // in-flight UI state - an old, superseded request's finally must
      // never stomp on a newer request's isSending/currentStage.
      if (requestIdRef.current === myRequestId) {
        clearTimeout(coldStartTimerRef.current)
        setIsSending(false)
        setIsColdStart(false)
        setCurrentStage(null)
      }
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
    : 'Ask a question about your documents…'

  const isEmpty = chatMessages.length === 0

  // A single shared empty-state block (heading + subtext, same icon/spacing/
  // container) drives every KB/readiness combination below — only the copy
  // and the optional trailing content (Demo's suggestion cards; none for
  // Your Documents) ever differ, so the container structure is never
  // conditionally skipped and the two knowledge bases can't drift out of
  // vertical alignment with each other.
  let emptyStateTitle
  let emptyStateSubtitle
  let emptyStateExtra = null

  if (isDemo) {
    emptyStateTitle = 'Ask anything about the demo documents'
    emptyStateSubtitle =
      "This knowledge base is pre-loaded and ready to answer questions. Or switch to Your " +
      'Documents in the sidebar to ask about your own files instead.'
    if (suggestedQuestions.length > 0) {
      emptyStateExtra = (
        <div className="chat-suggestions-panel">
          <h4 className="chat-suggestions-panel__title">
            <Sparkles size={16} aria-hidden="true" /> What can I ask?
          </h4>
          <p className="chat-suggestions-panel__subtitle">
            Here are some example questions based on the selected knowledge base.
          </p>
          <div className="chat-suggestions-panel__cards">
            {suggestedQuestions.map((question) => (
              <button
                key={question}
                type="button"
                className="chat-question-card"
                onClick={() => sendMessage(question)}
                disabled={isSending}
              >
                <span>{question}</span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
      )
    }
  } else if (hasReadyUserDocs) {
    const readyNames = readyUserDocuments.map((doc) => doc.filename)
    emptyStateTitle = 'Ask questions about your uploaded documents'
    emptyStateSubtitle =
      readyNames.length > 0
        ? `Ready to answer questions about: ${readyNames.join(', ')}.`
        : 'Ask a question about your uploaded documents.'
  } else if (userDocuments.length === 0) {
    emptyStateTitle = 'Upload a document to get started'
    emptyStateSubtitle =
      "You haven't uploaded anything yet. Try the Demo knowledge base above to see how this " +
      'works, or upload a PDF, DOCX, TXT, or MD file to start asking questions about your own.'
  } else {
    emptyStateTitle = 'Your documents are still processing'
    emptyStateSubtitle = 'Ask a question once at least one of your documents finishes processing.'
  }

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__thread">
        {isEmpty && <WelcomeHero />}

        {isEmpty && (
          <div className="chat-empty">
            <MessageSquare size={28} aria-hidden="true" className="chat-empty__icon" />
            <h3 className="chat-empty__title">{emptyStateTitle}</h3>
            <p className="chat-empty__subtitle">{emptyStateSubtitle}</p>
            {emptyStateExtra}
          </div>
        )}

        {chatMessages.map((message, index) => (
          <div key={index} className={`chat-message chat-message--${message.role}`}>
            {message.role === 'assistant' ? (
              <div className="chat-message__content chat-message__content--markdown">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            ) : (
              <p className="chat-message__content">{message.content}</p>
            )}
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
                    <FileSearch size={12} aria-hidden="true" />
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

        {isSending && (isColdStart || currentStage) && (
          <p className="chat-panel__status" role="status">
            <Loader2 size={14} aria-hidden="true" className="spin" />
            <span>
              {isColdStart
                ? 'Waking up the server, this can take up to a minute…'
                : STAGE_LABELS[currentStage]}
            </span>
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

      <form className="chat-panel__composer" onSubmit={handleSubmit}>
        <button
          type="button"
          className="chat-panel__attachment"
          aria-label="Attach documents"
          title="Manage documents"
          onClick={() => setView(VIEWS.DOCUMENTS)}
        >
          <Paperclip size={18} aria-hidden="true" />
        </button>
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
        <button
          type="submit"
          className="chat-panel__send"
          disabled={!isReady || isSending || !input.trim()}
          aria-label="Send"
        >
          <Send size={16} aria-hidden="true" />
          <span>Send</span>
        </button>
      </form>
      <p className="chat-panel__disclaimer">
        Answers are generated using the selected knowledge base. Always verify important
        information.
      </p>
    </section>
  )
}
