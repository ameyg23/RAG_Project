import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

function renderWithProvider(ui) {
  return render(<SessionProvider>{ui}</SessionProvider>)
}

describe('KnowledgeBaseSelector', () => {
  it('shows both the Demo and Your documents options', () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    expect(screen.getByRole('tab', { name: /demo/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /your documents/i })).toBeInTheDocument()
  })

  it('defaults to the Demo knowledge base selected', () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    expect(screen.getByRole('tab', { name: /demo/i })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows an empty hint for Your documents when it has no uploads', () => {
    renderWithProvider(<KnowledgeBaseSelector />)
    expect(screen.getByText(/empty, upload to get started/i)).toBeInTheDocument()
  })
})
