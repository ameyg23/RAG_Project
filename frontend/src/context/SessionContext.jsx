import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import {
  deleteDocument,
  getDocumentStatus,
  getHealth,
  listDocuments,
  listKnowledgeBases,
  setStoredSessionToken,
  uploadDocuments,
} from '../api/client'
import { DEMO_KB_ID } from '../constants'

const POLL_INTERVAL_MS = 2000

const SessionContext = createContext(null)

export function SessionProvider({ children }) {
  // Deliberately in-memory only (product decision): "Your Documents" is
  // session-scoped, so a fresh mount — a refresh, or reopening the tab —
  // must never resume a previous session's token. Nothing is read from
  // localStorage/sessionStorage here; a brand-new token is fetched below
  // via the /health effect every time this provider mounts.
  const [sessionToken, setSessionTokenState] = useState(null)
  const [activeKnowledgeBaseId, setActiveKnowledgeBaseIdState] = useState(DEMO_KB_ID)
  const [chatMessages, setChatMessages] = useState([])
  const [knowledgeBases, setKnowledgeBases] = useState([])
  // Canonical "your documents" list — the single source of truth every
  // consumer (Sidebar's compact DocumentsPanel, the full DocumentsView,
  // ChatPanel's ready/not-ready signal) reads from, instead of each owning
  // its own independent copy (see the frontend bugfix pass notes).
  const [userDocuments, setUserDocuments] = useState([])
  const pollTimersRef = useRef({})

  // Hands the current token to the API client so `request()` can attach it
  // as the X-Session-Token header — this is an in-memory sync only
  // (client.js keeps it in a plain module variable), never browser storage,
  // so it carries no persistence across a reload despite the name.
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

  const refetchUserDocuments = useCallback(async () => {
    if (!userKnowledgeBaseId) return
    try {
      const result = await listDocuments(userKnowledgeBaseId)
      setUserDocuments(result.documents ?? [])
    } catch {
      // Non-fatal — the shared list simply stays stale until the next
      // successful refetch; individual callers handle their own errors.
    }
  }, [userKnowledgeBaseId])

  // Backfill from real server state as soon as a "your documents" knowledge
  // base id exists (mirroring how `knowledgeBases` is fetched above), so a
  // fresh page load or a remount of any consumer never starts from an
  // artificially empty list even though the backend still has documents.
  useEffect(() => {
    if (userKnowledgeBaseId) refetchUserDocuments()
  }, [userKnowledgeBaseId, refetchUserDocuments])

  // Single polling loop per document, owned centrally here — mounting two
  // upload-UI instances (Sidebar's compact view + the full Documents view)
  // must never start two independent polling chains for the same document.
  // The recursive re-schedule goes through this ref (kept in sync just
  // below) rather than closing over `pollDocumentStatus` directly, so the
  // callback itself stays a normal, stably-memoized useCallback instead of a
  // self-referential one.
  const pollDocumentStatusRef = useRef(() => {})

  const pollDocumentStatus = useCallback(
    (documentId) => {
      getDocumentStatus(documentId)
        .then((result) => {
          setUserDocuments((prev) =>
            prev.map((doc) =>
              doc.document_id === documentId
                ? { ...doc, status: result.status, failure_reason: result.failure_reason }
                : doc
            )
          )
          if (result.status === 'READY' || result.status === 'FAILED') {
            delete pollTimersRef.current[documentId]
            refetchKnowledgeBases()
            return
          }
          pollTimersRef.current[documentId] = setTimeout(
            () => pollDocumentStatusRef.current(documentId),
            POLL_INTERVAL_MS
          )
        })
        .catch(() => {
          // Stop polling silently — the badge simply stops updating live,
          // not a fatal UI error (docs/UI_UX.md doesn't define a poll-failure
          // state distinct from the existing status badges).
          delete pollTimersRef.current[documentId]
        })
    },
    [refetchKnowledgeBases]
  )

  useEffect(() => {
    pollDocumentStatusRef.current = pollDocumentStatus
  }, [pollDocumentStatus])

  useEffect(() => {
    const timers = pollTimersRef.current
    return () => {
      Object.values(timers).forEach(clearTimeout)
    }
  }, [])

  const uploadUserDocuments = useCallback(
    async (files) => {
      const result = await uploadDocuments(files)
      if (result.session_token) setSessionTokenState(result.session_token)
      setUserDocuments((prev) => [...prev, ...(result.documents ?? [])])
      ;(result.documents ?? []).forEach((doc) => pollDocumentStatus(doc.document_id))
      refetchKnowledgeBases()
      return result
    },
    [pollDocumentStatus, refetchKnowledgeBases]
  )

  const deleteUserDocument = useCallback(
    async (documentId) => {
      await deleteDocument(documentId)
      clearTimeout(pollTimersRef.current[documentId])
      delete pollTimersRef.current[documentId]
      setUserDocuments((prev) => prev.filter((doc) => doc.document_id !== documentId))
      refetchKnowledgeBases()
    },
    [refetchKnowledgeBases]
  )

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
    userDocuments,
    refetchUserDocuments,
    uploadUserDocuments,
    deleteUserDocument,
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
