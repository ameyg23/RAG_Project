import { BookOpenText, Menu, Moon, Sun } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'
import { useView, VIEWS } from '../context/ViewContext'

const NAV_ITEMS = [
  { id: VIEWS.CHAT, label: 'Chat' },
  { id: VIEWS.DOCUMENTS, label: 'Documents' },
  { id: VIEWS.ABOUT, label: 'About' },
]

export default function Navbar({ onToggleSidebar }) {
  const { view, setView } = useView()
  const { theme, toggleTheme } = useTheme()

  return (
    <header className="navbar">
      <div className="navbar__section navbar__section--start">
        <button
          type="button"
          className="navbar__menu-toggle"
          aria-label="Toggle knowledge base sidebar"
          onClick={onToggleSidebar}
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <div className="navbar__brand">
          <BookOpenText size={22} aria-hidden="true" className="navbar__brand-icon" />
          <span>AI Knowledge Assistant</span>
        </div>
      </div>

      <nav className="navbar__nav" aria-label="Main">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`navbar__nav-item${view === item.id ? ' is-active' : ''}`}
            aria-current={view === item.id ? 'page' : undefined}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="navbar__section navbar__section--end">
        <button
          type="button"
          className="navbar__theme-toggle"
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          onClick={toggleTheme}
        >
          {theme === 'dark' ? (
            <Sun size={18} aria-hidden="true" />
          ) : (
            <Moon size={18} aria-hidden="true" />
          )}
        </button>
      </div>
    </header>
  )
}
