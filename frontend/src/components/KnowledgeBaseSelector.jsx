import { FolderOpen, Sparkles } from 'lucide-react'
import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

export default function KnowledgeBaseSelector() {
  const { activeKnowledgeBaseId, setActiveKnowledgeBaseId, userKnowledgeBaseId } = useSession()

  return (
    <div className="kb-selector">
      <h2 className="kb-selector__heading">Knowledge Base</h2>
      <div className="kb-selector__tabs" role="tablist" aria-label="Knowledge base">
        <button
          type="button"
          role="tab"
          aria-selected={activeKnowledgeBaseId === DEMO_KB_ID}
          className={`kb-badge kb-badge--demo${activeKnowledgeBaseId === DEMO_KB_ID ? ' is-active' : ''}`}
          onClick={() => setActiveKnowledgeBaseId(DEMO_KB_ID)}
        >
          <Sparkles size={16} aria-hidden="true" />
          <span>Demo Documents</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeKnowledgeBaseId === userKnowledgeBaseId}
          className={`kb-badge kb-badge--user${activeKnowledgeBaseId === userKnowledgeBaseId ? ' is-active' : ''}`}
          onClick={() => setActiveKnowledgeBaseId(userKnowledgeBaseId)}
        >
          <FolderOpen size={16} aria-hidden="true" />
          <span>Your Documents</span>
        </button>
      </div>
      {activeKnowledgeBaseId !== DEMO_KB_ID && (
        <p className="kb-selector__note">Starting a new conversation for this knowledge base.</p>
      )}
    </div>
  )
}
