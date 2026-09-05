import { useState } from 'react'
import { ApiError, uploadDocuments } from '../api/client'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

const MAX_FILES = 5
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'txt', 'md']

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
      <p className="documents-panel__empty">No documents in the demo knowledge base yet.</p>
    </div>
  )
}

function UserDocumentsView() {
  const [selectedFiles, setSelectedFiles] = useState([])
  const [validationError, setValidationError] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadedBatch, setUploadedBatch] = useState(null)

  function handleFileChange(event) {
    const files = Array.from(event.target.files ?? [])
    setSelectedFiles(files)
    setValidationError(validateFiles(files))
    setUploadError(null)
    setUploadedBatch(null)
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
      setUploadedBatch(result.documents)
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

  const hasDocuments = Boolean(uploadedBatch?.length)

  return (
    <div className="documents-panel documents-panel--user">
      <span className="kb-badge kb-badge--user">Your documents</span>

      {!hasDocuments && (
        <p className="documents-panel__empty">No documents yet. Upload one to get started.</p>
      )}

      {hasDocuments && (
        <ul className="documents-panel__list">
          {uploadedBatch.map((doc) => (
            <li key={doc.document_id}>
              {doc.filename} — <span className="status-badge">{doc.status}</span>
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
