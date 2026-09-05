import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { setStoredSessionToken } from '../api/client'
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

  useEffect(() => {
    setStoredSessionToken(sessionToken)
  }, [sessionToken])

  const setSessionToken = useCallback((token) => {
    setSessionTokenState(token)
  }, [])

  // Switching the active knowledge base always starts a fresh conversation
  // (FR-032) — callers only ever need to call this one setter.
  const setActiveKnowledgeBaseId = useCallback((knowledgeBaseId) => {
    setActiveKnowledgeBaseIdState(knowledgeBaseId)
    setChatMessages([])
  }, [])

  const value = {
    sessionToken,
    setSessionToken,
    activeKnowledgeBaseId,
    setActiveKnowledgeBaseId,
    chatMessages,
    setChatMessages,
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
