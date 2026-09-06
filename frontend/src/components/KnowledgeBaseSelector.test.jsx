import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, getHealth: vi.fn(), listKnowledgeBases: vi.fn(), listDocuments: vi.fn() }
})

import { getHealth, listDocuments, listKnowledgeBases } from '../api/client'

function mockDefaults({ userKb = null } = {}) {
  getHealth.mockResolvedValue({ status: 'ok', session_token: 'test-token', vector_store: 'connected' })
  const knowledgeBases = [
    { knowledge_base_id: 'kb_demo', kind: 'demo', name: 'Demo', document_count: 0, suggested_questions: [] },
  ]
  if (userKb) knowledgeBases.push(userKb)
  listKnowledgeBases.mockResolvedValue({ knowledge_bases: knowledgeBases })
  // SessionContext eagerly backfills the shared "your documents" list once a
  // session token exists — mock it so this doesn't hit the real network.
  listDocuments.mockResolvedValue({ knowledge_base_id: 'kb_user_test-token', documents: [] })
}

function renderWithProvider(ui) {
  return render(<SessionProvider>{ui}</SessionProvider>)
}

describe('KnowledgeBaseSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockDefaults()
  })

  it('shows both the Demo and Your documents options', async () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    expect(screen.getByRole('tab', { name: /demo/i })).toBeInTheDocument()
    expect(await screen.findByRole('tab', { name: /your documents/i })).toBeInTheDocument()
  })

  it('defaults to the Demo knowledge base selected', () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    expect(screen.getByRole('tab', { name: /demo/i })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows just "Your Documents" on the tab whether or not it has uploads', async () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    await waitFor(() => expect(getHealth).toHaveBeenCalled())
    const tab = await screen.findByRole('tab', { name: /your documents/i })
    expect(tab).toHaveTextContent(/^Your Documents$/)
  })

  it('still shows just "Your Documents" once the user knowledge base has documents', async () => {
    mockDefaults({
      userKb: {
        knowledge_base_id: 'kb_user_test-token',
        kind: 'user',
        name: 'Your documents',
        document_count: 2,
        suggested_questions: [],
      },
    })
    renderWithProvider(<KnowledgeBaseSelector />)
    await waitFor(() => expect(listKnowledgeBases).toHaveBeenCalled())
    const tab = await screen.findByRole('tab', { name: /your documents/i })
    expect(tab).toHaveTextContent(/^Your Documents$/)
  })
})
