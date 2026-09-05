import { DEMO_KB_ID } from '../constants'
import { useSession } from '../context/SessionContext'

// Phase 2: static placeholder KB list (no live listKnowledgeBases() call yet —
// Phase 16 wires this up for real). "Your documents" always starts empty
// until a real upload exists.
const USER_KB_ID = 'kb_user_placeholder'
const hasUserDocuments = false

export default function KnowledgeBaseSelector() {
  const { activeKnowledgeBaseId, setActiveKnowledgeBaseId } = useSession()

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
        aria-selected={activeKnowledgeBaseId === USER_KB_ID}
        className={`kb-badge kb-badge--user${activeKnowledgeBaseId === USER_KB_ID ? ' is-active' : ''}`}
        onClick={() => setActiveKnowledgeBaseId(USER_KB_ID)}
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
