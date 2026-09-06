import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from './SessionContext'

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
  deleteDocument,
  getDocumentStatus,
  getHealth,
  listDocuments,
  listKnowledgeBases,
  uploadDocuments,
} from '../api/client'

function mockDefaults({ initialDocuments = [] } = {}) {
  getHealth.mockResolvedValue({ status: 'ok', session_token: 'test-token', vector_store: 'connected' })
  listKnowledgeBases.mockResolvedValue({
    knowledge_bases: [
      {
        knowledge_base_id: 'kb_demo',
        kind: 'demo',
        name: 'Demo',
        document_count: 0,
        suggested_questions: [],
      },
    ],
  })
  listDocuments.mockResolvedValue({
    knowledge_base_id: 'kb_user_test-token',
    documents: initialDocuments,
  })
}

// A minimal consumer standing in for DocumentsPanel/ChatPanel — it only
// reads/writes through the context's public surface, never local state, so
// these tests exercise exactly what real consumers see.
function DocumentsProbe({ label = 'probe' }) {
  const { userDocuments, uploadUserDocuments, deleteUserDocument } = useSession()
  return (
    <div>
      <ul aria-label={`${label}-list`}>
        {userDocuments.map((doc) => (
          <li key={doc.document_id}>
            {doc.filename} — {doc.status}
          </li>
        ))}
      </ul>
      <button type="button" onClick={() => uploadUserDocuments([new File(['x'], 'probe.txt')])}>
        {label}-upload
      </button>
      <button type="button" onClick={() => deleteUserDocument('d1')}>
        {label}-delete
      </button>
    </div>
  )
}

// Exposes the raw token so tests can assert on it directly, distinct from
// DocumentsProbe above which only exercises the documents surface.
function TokenProbe() {
  const { sessionToken } = useSession()
  return <div data-testid="token">{sessionToken ?? '(none)'}</div>
}

describe('SessionContext session token persistence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('never reads a stale session token from localStorage on a fresh mount', async () => {
    // Seed localStorage as if a previous (pre-decision) build — or a stray
    // write from elsewhere — had left a token behind.
    localStorage.setItem('rag_session_token', 'stale-leftover-token')
    mockDefaults()

    render(
      <SessionProvider>
        <TokenProbe />
      </SessionProvider>
    )

    // A fresh mount always fetches a brand-new token from the backend via
    // /health rather than reusing anything from storage.
    expect(await screen.findByTestId('token')).toHaveTextContent('test-token')
    // And the provider never wrote anything back to localStorage either —
    // the seeded value sits untouched because nothing here reads or writes
    // browser storage for the session token any more.
    expect(localStorage.getItem('rag_session_token')).toBe('stale-leftover-token')
  })
})

describe('SessionContext user documents', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('backfills userDocuments from the server as soon as a session token is available', async () => {
    mockDefaults({
      initialDocuments: [
        { document_id: 'd1', filename: 'existing.txt', status: 'READY', failure_reason: null },
      ],
    })
    render(
      <SessionProvider>
        <DocumentsProbe />
      </SessionProvider>
    )
    // Nothing local was ever uploaded through this render — the array is
    // populated purely by the automatic fetch, proving a fresh mount is
    // backfilled from real server state instead of starting empty.
    expect(await screen.findByText(/existing\.txt — READY/)).toBeInTheDocument()
  })

  it('uploadUserDocuments merges the response into userDocuments, polls to READY in place, and refetches knowledge bases', async () => {
    mockDefaults()
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd2', filename: 'new.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({ document_id: 'd2', status: 'READY', failure_reason: null })

    render(
      <SessionProvider>
        <DocumentsProbe />
      </SessionProvider>
    )
    await waitFor(() => expect(listDocuments).toHaveBeenCalled())
    const knowledgeBaseCallsBeforeUpload = listKnowledgeBases.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: /probe-upload/i }))
    expect(await screen.findByText(/new\.txt — READY/)).toBeInTheDocument()

    // A document reaching READY/FAILED refetches the knowledge-base list
    // (so document_count-derived UI, e.g. the KB selector's empty hint,
    // updates too) — not just the document's own status badge.
    await waitFor(() =>
      expect(listKnowledgeBases.mock.calls.length).toBeGreaterThan(knowledgeBaseCallsBeforeUpload)
    )
  })

  it('deleteUserDocument removes the document from userDocuments', async () => {
    mockDefaults({
      initialDocuments: [
        { document_id: 'd1', filename: 'existing.txt', status: 'READY', failure_reason: null },
      ],
    })
    deleteDocument.mockResolvedValue({ document_id: 'd1', deleted: true })

    render(
      <SessionProvider>
        <DocumentsProbe />
      </SessionProvider>
    )
    await screen.findByText(/existing\.txt/)
    fireEvent.click(screen.getByRole('button', { name: /probe-delete/i }))

    await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith('d1'))
    expect(screen.queryByText(/existing\.txt/)).not.toBeInTheDocument()
  })

  it('keeps every mounted consumer in sync from one canonical array with exactly one polling chain', async () => {
    mockDefaults()
    uploadDocuments.mockResolvedValue({
      session_token: 'test-token',
      knowledge_base_id: 'kb_user_test-token',
      documents: [{ document_id: 'd3', filename: 'shared.txt', status: 'UPLOADED' }],
    })
    getDocumentStatus.mockResolvedValue({ document_id: 'd3', status: 'READY', failure_reason: null })

    // Two independently mounted consumers — standing in for the Sidebar's
    // compact DocumentsPanel and the full DocumentsView being mounted at
    // once, as they are in the real app.
    render(
      <SessionProvider>
        <DocumentsProbe label="a" />
        <DocumentsProbe label="b" />
      </SessionProvider>
    )
    await waitFor(() => expect(listDocuments).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /a-upload/i }))

    // Both consumers see the same upload and the same READY transition —
    // there is no per-instance copy that could go stale.
    expect(await screen.findAllByText(/shared\.txt — READY/)).toHaveLength(2)
    // Exactly one poll chain ran for this document (getDocumentStatus
    // resolves READY on its very first call) — a per-component polling
    // loop would have produced two calls, one per mounted instance.
    expect(getDocumentStatus).toHaveBeenCalledTimes(1)
  })
})
