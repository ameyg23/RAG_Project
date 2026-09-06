import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import ChatPanel from './ChatPanel'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getHealth: vi.fn(),
    listKnowledgeBases: vi.fn(),
    listDocuments: vi.fn(),
    sendChatMessage: vi.fn(),
  }
})

import { ApiError, getHealth, listDocuments, listKnowledgeBases, sendChatMessage } from '../api/client'

function mockDefaults({ suggestedQuestions = ['What is X?'], extraKbs = [] } = {}) {
  getHealth.mockResolvedValue({ status: 'ok', session_token: 'test-token', vector_store: 'connected' })
  listKnowledgeBases.mockResolvedValue({
    knowledge_bases: [
      {
        knowledge_base_id: 'kb_demo',
        kind: 'demo',
        name: 'Demo',
        document_count: 0,
        suggested_questions: suggestedQuestions,
      },
      ...extraKbs,
    ],
  })
  listDocuments.mockResolvedValue({ knowledge_base_id: 'kb_user_test-token', documents: [] })
}

// ADR-18: `sendChatMessage` is now a staged streaming consumer -
// `(knowledgeBaseId, message, conversationHistory, { onStage, signal })` -
// that calls `onStage(stage)` for each intermediate NDJSON event before
// resolving with `{answer, sources}` (or rejecting with an `ApiError`). This
// helper builds a mock implementation that fires a given sequence of stages
// (synchronously, as `sendChatMessage` itself would as each line streams in)
// before resolving/rejecting, matching the real contract closely enough for
// component-level testing.
function mockStagedChatResponse({ stages = [], result, error } = {}) {
  sendChatMessage.mockImplementationOnce(async (_kb, _message, _history, options = {}) => {
    for (const stage of stages) {
      options.onStage?.(stage)
    }
    if (error) throw error
    return result
  })
}

// For tests that need to control exactly when each stage/resolution fires
// (cold-start timing, one-stage-at-a-time rendering, concurrency), this
// captures the live `onStage` callback and a manual resolve/reject pair
// instead of letting the mock run straight through.
function deferredStagedChatResponse() {
  let onStage
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  sendChatMessage.mockImplementationOnce((_kb, _message, _history, options = {}) => {
    onStage = options.onStage
    return promise
  })
  return {
    fireStage: (stage) => act(() => onStage(stage)),
    resolve: (value) => act(async () => resolve(value)),
    reject: (err) => act(async () => reject(err)),
  }
}

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockDefaults()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('is never disabled for the demo knowledge base', () => {
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    expect(screen.getByRole('textbox')).not.toBeDisabled()
  })

  it('never pre-fills the composer with a question - the front-screen suggestion cards are the only place example questions are shown', async () => {
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    // Give any (would-be) async pre-fill effect a chance to run.
    await screen.findByRole('button', { name: /what is x\?/i })
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(sendChatMessage).not.toHaveBeenCalled()
  })

  it('clicking a front-screen suggested-question card sends it through the real chat API', async () => {
    mockStagedChatResponse({ result: { answer: 'The real answer.', sources: [] } })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('button', { name: /what is x\?/i }))
    expect(await screen.findByText(/the real answer/i)).toBeInTheDocument()
    expect(sendChatMessage).toHaveBeenCalledWith(
      'kb_demo',
      'What is X?',
      [],
      expect.objectContaining({ onStage: expect.any(Function) })
    )
  })

  it('sends a message and renders the answer with just its source document names', async () => {
    mockStagedChatResponse({
      result: {
        answer: 'The answer is 15.',
        sources: [
          {
            document_id: 'd1',
            document_name: 'doc.md',
            locator: 'chunk 1',
            snippet: 'the entire chunk text should never be rendered in the UI',
            is_removed: false,
          },
          {
            // A second citation from the same document should still only
            // render one source row, not a duplicate.
            document_id: 'd1',
            document_name: 'doc.md',
            locator: 'chunk 2',
            snippet: 'more chunk text that should also never be rendered',
            is_removed: false,
          },
        ],
      },
    })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'How many?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('How many?')).toBeInTheDocument()
    expect(await screen.findByText(/the answer is 15/i)).toBeInTheDocument()
    expect(screen.getAllByText('doc.md')).toHaveLength(1)
    expect(screen.queryByText('chunk 1')).not.toBeInTheDocument()
    expect(screen.queryByText(/entire chunk text/i)).not.toBeInTheDocument()
  })

  // ADR-18: the cold-start timer now clears on the FIRST stage event
  // received, not at the end of the whole request - so it only ever shows
  // while genuinely no progress signal has arrived yet.
  it('shows the cold-start message if no stage event arrives within 5 seconds', async () => {
    vi.useFakeTimers()
    const deferred = deferredStagedChatResponse()
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    // No stage has arrived yet and 5s hasn't passed - no status text at all.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.getByText(/waking up the server/i)).toBeInTheDocument()

    await deferred.resolve({ answer: 'done', sources: [] })
  })

  it('clears the cold-start message the instant the first stage event arrives, replacing it with the stage label', async () => {
    vi.useFakeTimers()
    const deferred = deferredStagedChatResponse()
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.getByText(/waking up the server/i)).toBeInTheDocument()

    deferred.fireStage('SEARCHING')
    expect(screen.queryByText(/waking up the server/i)).not.toBeInTheDocument()
    expect(screen.getByText(/searching documents/i)).toBeInTheDocument()

    await deferred.resolve({ answer: 'done', sources: [] })
  })

  it('disables the input for a user knowledge base with zero ready documents', async () => {
    mockDefaults({
      suggestedQuestions: [],
      extraKbs: [
        {
          knowledge_base_id: 'kb_user_test-token',
          kind: 'user',
          name: 'Your documents',
          document_count: 1,
          suggested_questions: [],
        },
      ],
    })
    listDocuments.mockResolvedValue({
      knowledge_base_id: 'kb_user_test-token',
      documents: [
        {
          document_id: 'd1',
          filename: 'f.txt',
          file_type: 'txt',
          size_bytes: 10,
          status: 'PROCESSING',
          failure_reason: null,
          uploaded_at: '2026-01-01T00:00:00Z',
          chunk_count: 0,
        },
      ],
    })

    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    expect(await screen.findByPlaceholderText(/no ready documents yet/i)).toBeDisabled()
  })

  // Phase 17: FR-054/FR-055 - LLM/vector-DB failures must show the sanitized
  // server message with a retry option, never a raw exception.
  it('shows a retryable error for a simulated LLM failure (502)', async () => {
    mockStagedChatResponse({
      stages: ['SEARCHING', 'RETRIEVING', 'GENERATING'],
      error: new ApiError(
        'LLM_UNAVAILABLE',
        'The answer service is temporarily unavailable. Please try again shortly.',
        502
      ),
    })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument()
    const retryButton = screen.getByRole('button', { name: /try again/i })
    expect(retryButton).toBeInTheDocument()

    mockStagedChatResponse({ result: { answer: 'Recovered answer.', sources: [] } })
    fireEvent.click(retryButton)
    expect(await screen.findByText(/recovered answer/i)).toBeInTheDocument()
  })

  // FR-054's error table treats 403 as non-retryable (a permissions problem,
  // not a transient one) - no "Try again" button should be offered for it.
  it('shows a non-retryable error with no retry button for a 403', async () => {
    mockStagedChatResponse({
      error: new ApiError('FORBIDDEN_KNOWLEDGE_BASE', 'You do not have access to this knowledge base.', 403),
    })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/do not have access/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  // ADR-18: a mid-stream ERROR event's `retryable` field (not just the HTTP
  // status, which no longer exists once a 200 stream has started) now
  // drives retryability - confirming VECTOR_STORE_UNAVAILABLE (new in
  // ADR-18) surfaces exactly like the pre-existing retryable paths.
  it('shows a retryable error for a mid-stream VECTOR_STORE_UNAVAILABLE event', async () => {
    mockStagedChatResponse({
      stages: ['SEARCHING'],
      error: new ApiError(
        'VECTOR_STORE_UNAVAILABLE',
        'The knowledge base search is temporarily unavailable. Please try again shortly.',
        200,
        true
      ),
    })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/knowledge base search is temporarily unavailable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  // ADR-18: a mid-stream INTERNAL_ERROR event is explicitly non-retryable.
  it('shows a non-retryable error with no retry button for a mid-stream INTERNAL_ERROR event', async () => {
    mockStagedChatResponse({
      stages: ['SEARCHING', 'RETRIEVING', 'GENERATING', 'VALIDATING'],
      error: new ApiError('INTERNAL_ERROR', 'An unexpected error occurred. Please try again shortly.', 200, false),
    })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/unexpected error occurred/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
    // The pipeline status must never get stuck on a stage when an error
    // fires - it must be gone, not left showing "Checking sources…".
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  // ADR-18: exactly one compact status message is shown at a time as real
  // stage events stream in, and it disappears the instant COMPLETED (i.e.
  // the resolved promise) arrives, replaced by the final answer.
  describe('staged pipeline progress (ADR-18)', () => {
    it('shows each stage label one at a time as its event fires, never more than one at once', async () => {
      const deferred = deferredStagedChatResponse()
      render(
        <SessionProvider>
          <ChatPanel />
        </SessionProvider>
      )
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
      fireEvent.click(screen.getByRole('button', { name: /send/i }))

      deferred.fireStage('SEARCHING')
      expect(screen.getByText(/searching documents/i)).toBeInTheDocument()
      expect(screen.getAllByRole('status')).toHaveLength(1)

      deferred.fireStage('RETRIEVING')
      expect(screen.queryByText(/searching documents/i)).not.toBeInTheDocument()
      expect(screen.getByText(/retrieving relevant information/i)).toBeInTheDocument()
      expect(screen.getAllByRole('status')).toHaveLength(1)

      deferred.fireStage('GENERATING')
      expect(screen.queryByText(/retrieving relevant information/i)).not.toBeInTheDocument()
      expect(screen.getByText(/generating answer/i)).toBeInTheDocument()
      expect(screen.getAllByRole('status')).toHaveLength(1)

      deferred.fireStage('VALIDATING')
      expect(screen.queryByText(/generating answer/i)).not.toBeInTheDocument()
      expect(screen.getByText(/checking sources/i)).toBeInTheDocument()
      expect(screen.getAllByRole('status')).toHaveLength(1)

      await deferred.resolve({ answer: 'Final answer.', sources: [] })
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      expect(await screen.findByText(/final answer/i)).toBeInTheDocument()
    })
  })

  // ADR-18 concurrency guard: a `requestIdRef` counter + `AbortController`
  // ensure a superseded request's late-arriving stage events can never
  // overwrite what a newer request has already displayed. Normal UI
  // disables the composer while a request is in flight (making this
  // unreachable through a real click), so this test drives the second
  // request directly through the form's submit event - a stand-in for the
  // fast-double-click/StrictMode-style race the mechanism defends against.
  it('only ever shows the newest request\'s stages, never a stale first-request stage', async () => {
    let onStageA
    const promiseA = new Promise(() => {}) // never resolves - request A is abandoned
    sendChatMessage.mockImplementationOnce((_kb, _message, _history, options = {}) => {
      onStageA = options.onStage
      return promiseA
    })

    const { container } = render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    const form = container.querySelector('form.chat-panel__composer')
    const textbox = screen.getByRole('textbox')

    fireEvent.change(textbox, { target: { value: 'First message' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    act(() => onStageA('SEARCHING'))
    expect(screen.getByText(/searching documents/i)).toBeInTheDocument()

    // Start a second request while the first is still in flight (bypassing
    // the disabled composer directly, per the note above).
    let onStageB
    let resolveB
    sendChatMessage.mockImplementationOnce((_kb, _message, _history, options = {}) => {
      onStageB = options.onStage
      return new Promise((resolve) => {
        resolveB = resolve
      })
    })
    fireEvent.change(textbox, { target: { value: 'Second message' } })
    fireEvent.submit(form)

    expect(sendChatMessage).toHaveBeenCalledTimes(2)

    // Starting request B clears request A's stage immediately - the status
    // line goes blank (rather than keeping A's stale "Searching documents…"
    // visible) until B's own first stage event arrives.
    expect(screen.queryByText(/searching documents/i)).not.toBeInTheDocument()

    // Request A's late stage event must never appear now that B has
    // superseded it.
    act(() => onStageA('RETRIEVING'))
    expect(screen.queryByText(/retrieving relevant information/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/searching documents/i)).not.toBeInTheDocument()

    act(() => onStageB('GENERATING'))
    expect(screen.queryByText(/searching documents/i)).not.toBeInTheDocument()
    expect(screen.getByText(/generating answer/i)).toBeInTheDocument()

    await act(async () => resolveB({ answer: 'Second answer.', sources: [] }))
    expect(await screen.findByText(/second answer/i)).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    // Request A resolving afterwards (abandoned tab semantics, ADR-18) must
    // not resurrect any UI state either.
    act(() => onStageA('GENERATING'))
    expect(screen.queryByText(/generating answer/i)).not.toBeInTheDocument()
  })

  // Regression test for the markdown-rendering bug: the LLM naturally
  // produces markdown (bullet lists, bold), and it must render as real
  // elements, not literal asterisks/dashes in the visible text.
  it('renders markdown in assistant answers as real lists and bold text, not literal syntax', async () => {
    mockStagedChatResponse({
      result: {
        answer:
          '**Key policies:**\n\n- Passwords must be rotated every 90 days [1]\n- 2FA is required for all accounts [2]',
        sources: [],
      },
    })
    const { container } = render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'What are the security policies?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await screen.findByText(/key policies/i)

    // Real elements, not raw markdown syntax.
    const bold = container.querySelector('.chat-message--assistant strong')
    expect(bold).toBeInTheDocument()
    expect(bold).toHaveTextContent('Key policies:')

    const items = container.querySelectorAll('.chat-message--assistant li')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Passwords must be rotated every 90 days [1]')
    expect(items[1]).toHaveTextContent('2FA is required for all accounts [2]')

    // No literal markdown syntax left over in the visible text.
    const assistantContent = container.querySelector('.chat-message--assistant .chat-message__content')
    expect(assistantContent.textContent).not.toMatch(/\*\*/)
    expect(assistantContent.textContent).not.toMatch(/^-\s|\n-\s/)
  })

  // A user's own typed message must never be markdown-parsed - e.g. typing a
  // literal "*" or "-" should show up exactly as typed, not turn into an
  // italic/bold span or a list item.
  it('never markdown-parses the user\'s own message', async () => {
    mockStagedChatResponse({ result: { answer: 'ok', sources: [] } })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '*is this bold* - not a list' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    const userMessage = await screen.findByText('*is this bold* - not a list')
    expect(userMessage.tagName).toBe('P')
    expect(userMessage.querySelector('strong, em, li')).toBeNull()
  })

  // ADR-16: the frontend sends recent conversation history alongside each
  // new message so the backend can resolve follow-up questions.
  describe('conversation history (ADR-16)', () => {
    it('sends an empty conversation history for the very first message of a fresh thread', async () => {
      mockStagedChatResponse({ result: { answer: 'First answer.', sources: [] } })
      render(
        <SessionProvider>
          <ChatPanel />
        </SessionProvider>
      )
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'First question?' } })
      fireEvent.click(screen.getByRole('button', { name: /send/i }))

      expect(await screen.findByText(/first answer/i)).toBeInTheDocument()
      expect(sendChatMessage).toHaveBeenCalledWith('kb_demo', 'First question?', [], expect.any(Object))
    })

    it('sends the prior user+assistant turn as history on a follow-up message, excluding the new message itself', async () => {
      mockStagedChatResponse({ result: { answer: 'First answer.', sources: [] } })
      render(
        <SessionProvider>
          <ChatPanel />
        </SessionProvider>
      )
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'First question?' } })
      fireEvent.click(screen.getByRole('button', { name: /send/i }))
      expect(await screen.findByText(/first answer/i)).toBeInTheDocument()

      mockStagedChatResponse({ result: { answer: 'Second answer.', sources: [] } })
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Follow-up question?' } })
      fireEvent.click(screen.getByRole('button', { name: /send/i }))

      expect(await screen.findByText(/second answer/i)).toBeInTheDocument()
      expect(sendChatMessage).toHaveBeenLastCalledWith(
        'kb_demo',
        'Follow-up question?',
        [
          { role: 'user', content: 'First question?' },
          { role: 'assistant', content: 'First answer.' },
        ],
        expect.any(Object)
      )
    })
  })
})
