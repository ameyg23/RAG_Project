import { useSession } from '../context/SessionContext'

// Phase 2: placeholder only — no live /chat wiring yet (Phase 16). The
// input is disabled because no knowledge base has any READY document yet
// (FR-056), which is honestly true right now (demo KB isn't seeded until
// Phase 4/5), not a fake restriction.
export default function ChatPanel() {
  const { chatMessages } = useSession()

  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-panel__thread">
        {chatMessages.length === 0 && (
          <p className="chat-panel__empty">Ask a question once this knowledge base has ready documents.</p>
        )}
      </div>
      <form className="chat-panel__composer" onSubmit={(e) => e.preventDefault()}>
        <input
          type="text"
          placeholder="This knowledge base has no ready documents yet."
          disabled
          aria-disabled="true"
        />
        <button type="submit" disabled>
          Send
        </button>
      </form>
    </section>
  )
}
