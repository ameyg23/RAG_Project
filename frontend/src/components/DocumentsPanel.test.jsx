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
    listDocuments: vi.fn(),
    uploadDocuments: vi.fn(),
    getDocumentStatus: vi.fn(),
    deleteDocument: vi.fn(),
  }
})

import {
  ApiError,
  deleteDocument,
  getDocumentStatus,
  getHealth,
  listDocuments,
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
  // SessionContext eagerly backfills the shared "your documents" list as
  // soon as a session token is available (Bug 1's canonical-source fix) —
  // default to empty so every test starts from a known, controlled state
  // instead of hitting the real (unmocked-here) network.
  listDocuments.mockResolvedValue({ knowledge_base_id: 'kb_user_test-token', documents: [] })
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

  // Phase 17: FR-050-056 error scenarios, client-side validation half.
  it('rejects an oversized file before ever calling the upload API', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    const bigFile = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'big.txt', {
      type: 'text/plain',
    })
    fireEvent.change(screen.getByLabelText(/upload documents/i), { target: { files: [bigFile] } })

    expect(screen.getByText(/larger than 5mb/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /upload/i })).toBeDisabled()
    expect(uploadDocuments).not.toHaveBeenCalled()
  })

  it('rejects an unsupported file type before ever calling the upload API', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    const badFile = new File(['x'], 'virus.exe', { type: 'application/octet-stream' })
    fireEvent.change(screen.getByLabelText(/upload documents/i), { target: { files: [badFile] } })

    expect(screen.getByText(/isn't a supported type/i)).toBeInTheDocument()
    expect(uploadDocuments).not.toHaveBeenCalled()
  })

  it('rejects more than 5 files before ever calling the upload API', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    const sixFiles = Array.from({ length: 6 }, (_, i) => makeFile(`f${i}.txt`))
    fireEvent.change(screen.getByLabelText(/upload documents/i), { target: { files: sixFiles } })

    expect(screen.getByText('You can upload up to 5 files at a time.')).toBeInTheDocument()
    expect(uploadDocuments).not.toHaveBeenCalled()
  })

  it('shows the sanitized server error message when the API rejects an upload', async () => {
    uploadDocuments.mockRejectedValue(
      new ApiError('UNSUPPORTED_FILE_TYPE', '"a.txt" has an unsupported file type.', 400)
    )
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))
    fireEvent.change(screen.getByLabelText(/upload documents/i), { target: { files: [makeFile()] } })
    fireEvent.click(screen.getByRole('button', { name: /upload/i }))

    expect(await screen.findByText(/unsupported file type/i)).toBeInTheDocument()
  })

  // New for the drag-and-drop dropzone: dropping files must feed the exact
  // same validate/upload code path as the file input, not a parallel one.
  it('accepts a dropped file through the same validate/upload path as the file input', async () => {
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd9', filename: 'dropped.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({ document_id: 'd9', status: 'READY', failure_reason: null })

    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    const dropzone = document.querySelector('.documents-panel__dropzone')
    const file = makeFile('dropped.txt')
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } })

    expect(screen.getByText(/1 of 5 files selected/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /upload/i }))

    expect(await screen.findByText(/READY/)).toBeInTheDocument()
    expect(uploadDocuments).toHaveBeenCalledWith([file])
  })

  it('rejects an oversized dropped file using the same validation as the file input', async () => {
    render(
      <SessionProvider>
        <KnowledgeBaseSelector />
        <DocumentsPanel />
      </SessionProvider>
    )
    fireEvent.click(await screen.findByRole('tab', { name: /your documents/i }))

    const dropzone = document.querySelector('.documents-panel__dropzone')
    const bigFile = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'big.txt', {
      type: 'text/plain',
    })
    fireEvent.drop(dropzone, { dataTransfer: { files: [bigFile] } })

    expect(screen.getByText(/larger than 5mb/i)).toBeInTheDocument()
    expect(uploadDocuments).not.toHaveBeenCalled()
  })
})
