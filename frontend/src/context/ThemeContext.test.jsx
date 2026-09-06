import { render, screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { ThemeProvider, useTheme } from './ThemeContext'

function ThemeProbe() {
  const { theme, toggleTheme } = useTheme()
  return (
    <button type="button" onClick={toggleTheme}>
      current: {theme}
    </button>
  )
}

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to light and applies data-theme to the document root', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    )
    expect(screen.getByText(/current: light/i)).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('toggling switches the theme, updates the DOM attribute, and persists it', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/current: dark/i)).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('rag_theme')).toBe('dark')
  })

  it('reads a persisted theme choice back on the next mount', () => {
    localStorage.setItem('rag_theme', 'dark')
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    )
    expect(screen.getByText(/current: dark/i)).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
