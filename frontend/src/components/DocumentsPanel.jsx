import {
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Trash2,
  UploadCloud,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ApiError, listDocuments } from '../api/client'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

const MAX_FILES = 5
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'txt', 'md']

// Labels intentionally keep the raw enum text (not friendlier casing) — the
// status model/values are untouched per decision #8, this is presentation
// (pill + icon) layered on top of the same four enum strings.
const STATUS_META = {
  UPLOADED: { label: 'UPLOADED', icon: Clock, className: 'status-pill--uploaded' },
  PROCESSING: { label: 'PROCESSING', icon: Loader2, className: 'status-pill--processing' },
  READY: { label: 'READY', icon: CheckCircle2, className: 'status-pill--ready' },
  FAILED: { label: 'FAILED', icon: XCircle, className: 'status-pill--failed' },
}

function StatusPill({ status }) {
  const meta = STATUS_META[status] ?? { label: status, icon: Clock, className: '' }
  const Icon = meta.icon
  return (
    <span className={`status-pill ${meta.className}`}>
      <Icon size={13} aria-hidden="true" className={status === 'PROCESSING' ? 'spin' : undefined} />
      {meta.label}
    </span>
  )
}

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

function DemoDocumentsView({ compact }) {
  const [documents, setDocuments] = useState([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    listDocuments(DEMO_KB_ID)
      .then((result) => {
        if (!cancelled) setDocuments(result.documents ?? [])
      })
      .catch(() => {
        // Non-fatal: the panel just shows the generic intro line below
        // instead of a real document list if this fails.
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="documents-panel documents-panel--demo">
      {!compact && (
        <>
          <h3 className="documents-panel__title">
            Demo Documents{!isLoading && documents.length > 0 ? ` (${documents.length})` : ''}
          </h3>
          <p className="documents-panel__empty">
            This knowledge base is pre-loaded with demo content and is always ready to answer
            questions.
          </p>
        </>
      )}
      {!isLoading && documents.length > 0 && (
        <ul className="documents-panel__list documents-panel__list--readonly">
          {documents.map((doc) => (
            <li key={doc.document_id}>
              <FileText size={16} aria-hidden="true" className="documents-panel__file-icon" />
              <span className="documents-panel__filename">{doc.filename}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function UserDocumentsView({ compact }) {
  const { userDocuments, uploadUserDocuments, deleteUserDocument } = useSession()

  const [selectedFiles, setSelectedFiles] = useState([])
  const [validationError, setValidationError] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isDragActive, setIsDragActive] = useState(false)
  const fileInputRef = useRef(null)

  // Shared by both the native file input and drag-and-drop — one validation/
  // selection code path regardless of how the files arrived.
  function handleFilesSelected(files) {
    setSelectedFiles(files)
    setValidationError(validateFiles(files))
    setUploadError(null)
  }

  function handleFileChange(event) {
    handleFilesSelected(Array.from(event.target.files ?? []))
  }

  function handleDragOver(event) {
    event.preventDefault()
    setIsDragActive(true)
  }

  function handleDragLeave(event) {
    event.preventDefault()
    setIsDragActive(false)
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragActive(false)
    const files = Array.from(event.dataTransfer?.files ?? [])
    if (files.length === 0) return
    handleFilesSelected(files)
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
      await uploadUserDocuments(selectedFiles)
      setSelectedFiles([])
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
      await deleteUserDocument(documentId)
    } catch {
      // Non-fatal for this simple UI — the document stays listed if delete
      // fails; the user can retry the delete action.
    }
  }

  const hasDocuments = userDocuments.length > 0

  return (
    <div className="documents-panel documents-panel--user">
      {!compact && (
        <h3 className="documents-panel__title">
          Your Documents{hasDocuments ? ` (${userDocuments.length})` : ''}
        </h3>
      )}

      {!hasDocuments && (
        <p className="documents-panel__empty">No documents yet. Upload one to get started.</p>
      )}

      {hasDocuments && (
        <ul className="documents-panel__list">
          {userDocuments.map((doc) => (
            <li key={doc.document_id}>
              <FileText size={16} aria-hidden="true" className="documents-panel__file-icon" />
              <span className="documents-panel__filename">{doc.filename}</span>
              <StatusPill status={doc.status} />
              <button
                type="button"
                className="documents-panel__delete"
                aria-label={`Delete ${doc.filename}`}
                onClick={() => handleDelete(doc.document_id)}
              >
                <Trash2 size={14} aria-hidden="true" />
              </button>
              {doc.status === 'FAILED' && doc.failure_reason && (
                <p className="documents-panel__failure-reason">{doc.failure_reason}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {!compact && (
        <form className="documents-panel__upload" onSubmit={handleSubmit}>
          <h4 className="documents-panel__upload-title">Upload your documents</h4>
          <div
            className={`documents-panel__dropzone${isDragActive ? ' is-drag-active' : ''}`}
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <UploadCloud size={28} aria-hidden="true" className="documents-panel__dropzone-icon" />
            <p className="documents-panel__dropzone-text">Drag &amp; drop your documents here</p>
            <button
              type="button"
              className="documents-panel__browse"
              onClick={() => fileInputRef.current?.click()}
            >
              Browse files
            </button>
            <p className="documents-panel__dropzone-hint">
              PDF, DOCX, TXT, MD · Up to {MAX_FILES} files · Up to 5MB each
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md"
              onChange={handleFileChange}
              aria-label="Upload documents"
              className="documents-panel__file-input"
            />
          </div>
          {selectedFiles.length > 0 && (
            <p className="documents-panel__count">
              {selectedFiles.length} of {MAX_FILES} files selected
            </p>
          )}
          {validationError && <p className="documents-panel__error">{validationError}</p>}
          {uploadError && <p className="documents-panel__error">{uploadError}</p>}
          <button
            type="submit"
            className="documents-panel__submit"
            disabled={selectedFiles.length === 0 || Boolean(validationError) || isUploading}
          >
            {isUploading ? 'Uploading…' : 'Upload'}
          </button>
        </form>
      )}
    </div>
  )
}

export default function DocumentsPanel({ compact = false }) {
  const { activeKnowledgeBaseId } = useSession()
  return activeKnowledgeBaseId === DEMO_KB_ID ? (
    <DemoDocumentsView compact={compact} />
  ) : (
    <UserDocumentsView compact={compact} />
  )
}
