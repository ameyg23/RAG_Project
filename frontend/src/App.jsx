import ChatPanel from './components/ChatPanel'
import DocumentsPanel from './components/DocumentsPanel'
import KnowledgeBaseSelector from './components/KnowledgeBaseSelector'
import { SessionProvider } from './context/SessionContext'
import './App.css'

function AppShell() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>RAG Chatbot</h1>
        <p className="app-header__tagline">
          Ask questions about a demo document set, or upload your own and chat with it — every
          answer is backed by a source citation.
        </p>
        <KnowledgeBaseSelector />
      </header>
      <main className="app-main">
        <DocumentsPanel />
        <ChatPanel />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <AppShell />
    </SessionProvider>
  )
}
