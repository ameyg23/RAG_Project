import { useEffect, useRef, useState } from 'react'
import { ApiError, deleteDocument, getDocumentStatus, uploadDocuments } from '../api/client'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

const MAX_FILES = 5
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'txt', 'md']
const POLL_INTERVAL_MS = 2000

function fileExtension(filename) {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

// Client-side validation only (server re-validates identically — docs/API.md).
function validateFiles(files) {
  if (files.length === 0) return 'Select at least one file.'
  if (files.length > MAX_FILES) return `You can upload up to ${MAX_FILES} files at a time.`
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `"${file.name}" is larger than 5MB.`
    }
    if (!ALLOWED_EXTENSIONS.includes(fileExtension(file.name))) {
      return `"${file.name}" isn't a supported type. Supported: PDF, DOCX, TXT, MD.`
    }
  }
  return null
}

function DemoDocumentsView() {
  return (
    <div className="documents-panel documents-panel--demo">
      <span className="kb-badge kb-badge--demo">Demo</span>
      <p className="documents-panel__empty">
        This knowledge base is pre-loaded with demo content and is always ready to answer
        questions.
      </p>
    </div>
  )
}

function UserDocumentsView() {
  const { setSessionToken, refetchKnowledgeBases } = useSession()

  const [selectedFiles, setSelectedFiles] = useState([])
  const [validationError, setValidationError] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [documents, setDocuments] = useState([])
  const pollTimersRef = useRef({})

  useEffect(() => {
    const timers = pollTimersRef.current
    return () => {
      Object.values(timers).forEach(clearTimeout)
    }
  }, [])

  function pollStatus(documentId) {
    getDocumentStatus(documentId)
      .then((result) => {
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.document_id === documentId
              ? { ...doc, status: result.status, failure_reason: result.failure_reason }
              : doc
          )
        )
        if (result.status === 'READY' || result.status === 'FAILED') {
          refetchKnowledgeBases()
          return
        }
        pollTimersRef.current[documentId] = setTimeout(() => pollStatus(documentId), POLL_INTERVAL_MS)
      })
      .catch(() => {
        // Stop polling silently — the badge simply stops updating live,
        // not a fatal UI error (docs/UI_UX.md doesn't define a poll-failure
        // state distinct from the existing status badges).
      })
  }

  function handleFileChange(event) {
    const files = Array.from(event.target.files ?? [])
    setSelectedFiles(files)
    setValidationError(validateFiles(files))
    setUploadError(null)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const error = validateFiles(selectedFiles)
    if (error) {
      setValidationError(error)
      return
    }
    setIsUploading(true)
    setUploadError(null)
    try {
      const result = await uploadDocuments(selectedFiles)
      if (result.session_token) setSessionToken(result.session_token)
      setDocuments((prev) => [...prev, ...result.documents])
      setSelectedFiles([])
      result.documents.forEach((doc) => pollStatus(doc.document_id))
      refetchKnowledgeBases()
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't reach the server. Check your connection and try again."
      setUploadError(message)
    } finally {
      setIsUploading(false)
    }
  }

  async function handleDelete(documentId) {
    try {
      await deleteDocument(documentId)
      clearTimeout(pollTimersRef.current[documentId])
      delete pollTimersRef.current[documentId]
      setDocuments((prev) => prev.filter((doc) => doc.document_id !== documentId))
      refetchKnowledgeBases()
    } catch {
      // Non-fatal for this simple UI — the document stays listed if delete
      // fails; the user can retry the delete action.
    }
  }

  const hasDocuments = documents.length > 0

  return (
    <div className="documents-panel documents-panel--user">
      <span className="kb-badge kb-badge--user">Your documents</span>

      {!hasDocuments && (
        <p className="documents-panel__empty">No documents yet. Upload one to get started.</p>
      )}

      {hasDocuments && (
        <ul className="documents-panel__list">
          {documents.map((doc) => (
            <li key={doc.document_id}>
              {doc.filename} — <span className="status-badge">{doc.status}</span>
              {doc.status === 'FAILED' && doc.failure_reason && (
                <p className="documents-panel__failure-reason">{doc.failure_reason}</p>
              )}
              <button
                type="button"
                className="documents-panel__delete"
                aria-label={`Delete ${doc.filename}`}
                onClick={() => handleDelete(doc.document_id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="documents-panel__upload" onSubmit={handleSubmit}>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          onChange={handleFileChange}
          aria-label="Upload documents"
        />
        <p className="documents-panel__hint">Files are re-checked on upload.</p>
        {selectedFiles.length > 0 && (
          <p className="documents-panel__count">
            {selectedFiles.length} of {MAX_FILES} files selected
          </p>
        )}
        {validationError && <p className="documents-panel__error">{validationError}</p>}
        {uploadError && <p className="documents-panel__error">{uploadError}</p>}
        <button
          type="submit"
          disabled={selectedFiles.length === 0 || Boolean(validationError) || isUploading}
        >
          {isUploading ? 'Uploading…' : 'Upload'}
        </button>
      </form>
    </div>
  )
}

export default function DocumentsPanel() {
  const { activeKnowledgeBaseId } = useSession()
  return activeKnowledgeBaseId === DEMO_KB_ID ? <DemoDocumentsView /> : <UserDocumentsView />
}
