import DocumentsPanel from './DocumentsPanel'

// The "Documents" nav view foregrounds document management by giving the
// exact same DocumentsPanel component (upload/list/delete logic untouched)
// a full-width, full-height home instead of the sidebar's compact slot.
export default function DocumentsView() {
  return (
    <div className="documents-view">
      <DocumentsPanel />
    </div>
  )
}
