import { X } from 'lucide-react'
import { useSession } from '../context/SessionContext'
import { useView, VIEWS } from '../context/ViewContext'
import DocumentsPanel from './DocumentsPanel'
import KnowledgeBaseSelector from './KnowledgeBaseSelector'

export default function Sidebar({ isOpen, onClose }) {
  const { view } = useView()
  const { activeKnowledgeBaseId } = useSession()

  return (
    <>
      {isOpen && <div className="sidebar-scrim" onClick={onClose} aria-hidden="true" />}
      <aside
        id="app-sidebar"
        className={`sidebar${isOpen ? ' is-open' : ''}`}
        aria-label="Knowledge base sidebar"
      >
        <button type="button" className="sidebar__close" aria-label="Close sidebar" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
        <KnowledgeBaseSelector />
        {/* The Documents view already shows the full document list with more
            room, so the sidebar mirrors it (list + delete, no upload form)
            only while some other view is active — avoiding two independently
            stateful copies of the same list on screen at once. */}
        {view !== VIEWS.DOCUMENTS && (
          <div className="sidebar__documents" key={activeKnowledgeBaseId}>
            <DocumentsPanel compact />
          </div>
        )}
      </aside>
    </>
  )
}
