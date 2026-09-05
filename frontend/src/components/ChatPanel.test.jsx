import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import ChatPanel, { META_PROMPT } from './ChatPanel'
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

import { getHealth, listDocuments, listKnowledgeBases, sendChatMessage } from '../api/client'

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

  it('pre-fills the composer with the meta-question on landing, not yet sent', async () => {
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    expect(await screen.findByDisplayValue(META_PROMPT)).toBeInTheDocument()
    expect(sendChatMessage).not.toHaveBeenCalled()
    expect(listDocuments).not.toHaveBeenCalledWith('kb_demo')
  })

  it('sending the meta-question answers client-side with document names and real questions, never calling the real chat API', async () => {
    listDocuments.mockImplementation((kbId) =>
      kbId === 'kb_demo'
        ? Promise.resolve({
            knowledge_base_id: 'kb_demo',
            documents: [{ document_id: 'd1', filename: 'handbook.md' }],
          })
        : Promise.resolve({ knowledge_base_id: kbId, documents: [] })
    )
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    await screen.findByDisplayValue(META_PROMPT)
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/handbook\.md/i)).toBeInTheDocument()
    expect(screen.getByText(/• What is X\?/)).toBeInTheDocument()
    expect(sendChatMessage).not.toHaveBeenCalled()
  })

  it('shows suggested question chips only after the first message is sent, not before', async () => {
    sendChatMessage.mockResolvedValue({ answer: 'answer', sources: [] })
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    await screen.findByDisplayValue(META_PROMPT)
    expect(screen.queryByRole('button', { name: /what is x\?/i })).not.toBeInTheDocument()

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'A real question' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText(/answer/i)

    expect(await screen.findByRole('button', { name: /what is x\?/i })).toBeInTheDocument()
  })

  it('sends a message and renders the answer with just its source document names', async () => {
    sendChatMessage.mockResolvedValue({
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

  it('shows the cold-start message if the response takes longer than 5 seconds', async () => {
    vi.useFakeTimers()
    let resolveChat
    sendChatMessage.mockReturnValue(
      new Promise((resolve) => {
        resolveChat = resolve
      })
    )
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    // Fake timers are active, so synchronous getByText (not findByText's
    // real-timer polling, which would hang forever here) is used throughout.
    expect(screen.getByText(/thinking/i)).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.getByText(/waking up the server/i)).toBeInTheDocument()

    resolveChat({ answer: 'done', sources: [] })
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
})
