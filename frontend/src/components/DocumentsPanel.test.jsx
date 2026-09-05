import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import DocumentsPanel from './DocumentsPanel'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

describe('DocumentsPanel', () => {
  it('shows the demo read-only empty state by default (no upload/delete controls)', () => {
    render(
      <SessionProvider>
        <DocumentsPanel />
      </SessionProvider>
    )
    expect(screen.getByText(/no documents in the demo knowledge base yet/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/upload documents/i)).not.toBeInTheDocument()
  })

  it('shows the "No documents yet" empty state with an upload control for Your documents', () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(screen.getByRole('tab', { name: /your documents/i }))
    expect(screen.getByText(/no documents yet\. upload one to get started/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/upload documents/i)).toBeInTheDocument()
  })

  it('disables the upload submit button until valid files are selected', () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(screen.getByRole('tab', { name: /your documents/i }))
    expect(screen.getByRole('button', { name: /upload/i })).toBeDisabled()
  })
})
