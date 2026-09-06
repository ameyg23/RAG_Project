import { createContext, useContext, useState } from 'react'

// Three static views (Chat / Documents / About), local view-state switching —
// no react-router-dom, there's no need for real routes here.
export const VIEWS = { CHAT: 'chat', DOCUMENTS: 'documents', ABOUT: 'about' }

// Default value (rather than null + a throwing hook) so components that use
// a view-switching affordance (e.g. ChatPanel's attachment button) keep
// working standalone in existing component tests that render them without a
// ViewProvider — they just get a harmless no-op setView.
const ViewContext = createContext({ view: VIEWS.CHAT, setView: () => {} })

export function ViewProvider({ children }) {
  const [view, setView] = useState(VIEWS.CHAT)
  return <ViewContext.Provider value={{ view, setView }}>{children}</ViewContext.Provider>
}

export function useView() {
  return useContext(ViewContext)
}
