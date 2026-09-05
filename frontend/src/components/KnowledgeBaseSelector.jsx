import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

export default function KnowledgeBaseSelector() {
  const { activeKnowledgeBaseId, setActiveKnowledgeBaseId, userKnowledgeBaseId, knowledgeBases } =
    useSession()

  const userKb = knowledgeBases.find((kb) => kb.knowledge_base_id === userKnowledgeBaseId)
  const hasUserDocuments = Boolean(userKb && userKb.document_count > 0)

  return (
    <div className="kb-selector" role="tablist" aria-label="Knowledge base">
      <button
        type="button"
        role="tab"
        aria-selected={activeKnowledgeBaseId === DEMO_KB_ID}
        className={`kb-badge kb-badge--demo${activeKnowledgeBaseId === DEMO_KB_ID ? ' is-active' : ''}`}
        onClick={() => setActiveKnowledgeBaseId(DEMO_KB_ID)}
      >
        Demo
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={activeKnowledgeBaseId === userKnowledgeBaseId}
        className={`kb-badge kb-badge--user${activeKnowledgeBaseId === userKnowledgeBaseId ? ' is-active' : ''}`}
        onClick={() => userKnowledgeBaseId && setActiveKnowledgeBaseId(userKnowledgeBaseId)}
      >
        Your documents
        {!hasUserDocuments && <span className="kb-badge__hint"> — Empty, upload to get started</span>}
      </button>
      {activeKnowledgeBaseId !== DEMO_KB_ID && (
        <p className="kb-selector__note">Starting a new conversation for this knowledge base.</p>
      )}
    </div>
  )
}
