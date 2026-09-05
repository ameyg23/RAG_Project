import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getHealth, listKnowledgeBases, setStoredSessionToken } from '../api/client'
import { DEMO_KB_ID } from '../constants'

const SESSION_TOKEN_STORAGE_KEY = 'rag_session_token'

const SessionContext = createContext(null)

export function SessionProvider({ children }) {
  const [sessionToken, setSessionTokenState] = useState(() => {
    try {
      return localStorage.getItem(SESSION_TOKEN_STORAGE_KEY)
    } catch {
      return null
    }
  })
  const [activeKnowledgeBaseId, setActiveKnowledgeBaseIdState] = useState(DEMO_KB_ID)
  const [chatMessages, setChatMessages] = useState([])
  const [knowledgeBases, setKnowledgeBases] = useState([])

  useEffect(() => {
    setStoredSessionToken(sessionToken)
  }, [sessionToken])

  const setSessionToken = useCallback((token) => {
    setSessionTokenState(token)
  }, [])

  const refetchKnowledgeBases = useCallback(async () => {
    try {
      const result = await listKnowledgeBases()
      setKnowledgeBases(result.knowledge_bases ?? [])
    } catch {
      // Non-fatal — the shared list simply stays stale until the next
      // successful refetch; individual callers handle their own errors.
    }
  }, [])

  // Eagerly establish a session token on first load (ARCHITECTURE.md §2 —
  // a session token is issued on first contact), so a stable "your
  // documents" knowledge-base id is available even before the visitor's
  // first upload, rather than only being known after they upload something.
  useEffect(() => {
    if (sessionToken) return
    let cancelled = false
    getHealth()
      .then((result) => {
        if (!cancelled && result?.session_token) {
          setSessionTokenState(result.session_token)
        }
      })
      .catch(() => {
        // Non-fatal — a token will also be issued by the first upload
        // response if this eager fetch fails.
      })
    return () => {
      cancelled = true
    }
  }, [sessionToken])

  useEffect(() => {
    refetchKnowledgeBases()
  }, [sessionToken, refetchKnowledgeBases])

  // Switching the active knowledge base always starts a fresh conversation
  // (FR-032) — callers only ever need to call this one setter.
  const setActiveKnowledgeBaseId = useCallback((knowledgeBaseId) => {
    setActiveKnowledgeBaseIdState(knowledgeBaseId)
    setChatMessages([])
  }, [])

  const userKnowledgeBaseId = sessionToken ? `kb_user_${sessionToken}` : null

  const value = {
    sessionToken,
    setSessionToken,
    userKnowledgeBaseId,
    activeKnowledgeBaseId,
    setActiveKnowledgeBaseId,
    chatMessages,
    setChatMessages,
    knowledgeBases,
    refetchKnowledgeBases,
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const context = useContext(SessionContext)
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider')
  }
  return context
}
