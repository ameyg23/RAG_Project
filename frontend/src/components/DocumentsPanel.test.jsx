import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import DocumentsPanel from './DocumentsPanel'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getHealth: vi.fn(),
    listKnowledgeBases: vi.fn(),
    uploadDocuments: vi.fn(),
    getDocumentStatus: vi.fn(),
    deleteDocument: vi.fn(),
  }
})

import {
  deleteDocument,
  getDocumentStatus,
  getHealth,
  listKnowledgeBases,
  uploadDocuments,
} from '../api/client'

function mockDefaults() {
  getHealth.mockResolvedValue({ status: 'ok', session_token: 'test-token', vector_store: 'connected' })
  listKnowledgeBases.mockResolvedValue({
    knowledge_bases: [
      { knowledge_base_id: 'kb_demo', kind: 'demo', name: 'Demo', document_count: 0, suggested_questions: [] },
    ],
  })
}

function makeFile(name = 'a.txt') {
  return new File(['content'], name, { type: 'text/plain' })
}

describe('DocumentsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockDefaults()
  })

  it('shows the demo read-only state by default (no upload/delete controls)', () => {
    render(
      <SessionProvider>
        <DocumentsPanel />
      </SessionProvider>
    )
    expect(screen.getByText(/pre-loaded with demo content/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/upload documents/i)).not.toBeInTheDocument()
  })

  it('shows the "No documents yet" empty state with an upload control for Your documents', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    expect(screen.getByText(/no documents yet\. upload one to get started/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/upload documents/i)).toBeInTheDocument()
  })

  it('disables the upload submit button until valid files are selected', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    expect(screen.getByRole('button', { name: /upload/i })).toBeDisabled()
  })

  it('shows a live status transition to READY after upload and polling', async () => {
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd1', filename: 'a.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({ document_id: 'd1', status: 'READY', failure_reason: null })

    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    fireEvent.change(screen.getByLabelText(/upload documents/i), { target: { files: [makeFile()] } })
    fireEvent.click(screen.getByRole('button', { name: /upload/i }))

    expect(await screen.findByText(/READY/)).toBeInTheDocument()
  })

  it('shows the failure reason for a document that ends up FAILED', async () => {
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd2', filename: 'b.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({
      document_id: 'd2',
      status: 'FAILED',
      failure_reason: 'No extractable text found (file may be a scanned image).',
    })

    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    fireEvent.change(screen.getByLabelText(/upload documents/i), {
      target: { files: [makeFile('b.txt')] },
    })
    fireEvent.click(screen.getByRole('button', { name: /upload/i }))

    expect(await screen.findByText(/no extractable text found/i)).toBeInTheDocument()
  })

  it('deletes a document when its delete control is clicked', async () => {
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd3', filename: 'c.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({ document_id: 'd3', status: 'READY', failure_reason: null })
    deleteDocument.mockResolvedValue({ document_id: 'd3', deleted: true })

    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    fireEvent.change(screen.getByLabelText(/upload documents/i), {
      target: { files: [makeFile('c.txt')] },
    })
    fireEvent.click(screen.getByRole('button', { name: /upload/i }))

    await screen.findByText(/READY/)
    expect(screen.getByText(/c\.txt/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /delete c\.txt/i }))

    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith('d3'))
    expect(screen.queryByText(/c\.txt/)).not.toBeInTheDocument()
  })
})
