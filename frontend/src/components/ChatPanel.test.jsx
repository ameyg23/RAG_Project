import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import ChatPanel from './ChatPanel'

describe('ChatPanel', () => {
  it('renders a disabled input when the active knowledge base has no ready documents', () => {
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    expect(screen.getByPlaceholderText(/no ready documents yet/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })

  it('shows an empty-thread placeholder message', () => {
    render(
      <SessionProvider>
        <ChatPanel />
      </SessionProvider>
    )
    expect(screen.getByText(/ask a question once this knowledge base has ready documents/i)).toBeInTheDocument()
  })
})
