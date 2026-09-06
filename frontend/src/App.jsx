import { useState } from 'react'
import AboutView from './components/AboutView'
import ChatPanel from './components/ChatPanel'
import DocumentsView from './components/DocumentsView'
import Navbar from './components/Navbar'
import Sidebar from './components/Sidebar'
import { SessionProvider } from './context/SessionContext'
import { ThemeProvider } from './context/ThemeContext'
import { useView, ViewProvider, VIEWS } from './context/ViewContext'
import './App.css'

function MainContent() {
  const { view } = useView()
  if (view === VIEWS.DOCUMENTS) return <DocumentsView />
  if (view === VIEWS.ABOUT) return <AboutView />
  return <ChatPanel />
}

function AppShell() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  return (
    <div className="app-shell">
      <Navbar onToggleSidebar={() => setIsSidebarOpen((open) => !open)} />
      <div className="app-body">
        <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
        <main className="app-main">
          <MainContent />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ViewProvider>
        <SessionProvider>
          <AppShell />
        </SessionProvider>
      </ViewProvider>
    </ThemeProvider>
  )
}
