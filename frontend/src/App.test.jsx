import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, getHealth: vi.fn(), listKnowledgeBases: vi.fn(), listDocuments: vi.fn() }
})

import { getHealth, listDocuments, listKnowledgeBases } from './api/client'

function mockDefaults() {
  getHealth.mockResolvedValue({ status: 'ok', session_token: 'test-token', vector_store: 'connected' })
  listKnowledgeBases.mockResolvedValue({
    knowledge_bases: [
      { knowledge_base_id: 'kb_demo', kind: 'demo', name: 'Demo', document_count: 0, suggested_questions: [] },
    ],
  })
  listDocuments.mockResolvedValue({ knowledge_base_id: 'kb_demo', documents: [] })
}

describe('App view switching', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    mockDefaults()
  })

  it('shows the Chat view by default', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /^chat$/i })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('switches to the Documents view when its nav item is clicked', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /^documents$/i }))
    expect(screen.getByRole('button', { name: /^documents$/i })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('switches to the About view when its nav item is clicked', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /^about$/i }))
    expect(screen.getByText(/about ai knowledge assistant/i)).toBeInTheDocument()
  })

  it("clicking the chat composer's attachment button switches to the Documents view", () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /attach documents/i }))
    expect(screen.getByRole('button', { name: /^documents$/i })).toHaveAttribute('aria-current', 'page')
  })
})
