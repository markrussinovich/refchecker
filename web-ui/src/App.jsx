import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar/Sidebar'
import MainPanel from './components/MainPanel/MainPanel'
import DebugPanel from './components/DebugPanel'
import LiveWebSocketManager from './components/LiveWebSocketManager'
import SettingsPanel from './components/Settings/SettingsPanel'
import { logger } from './utils/logger'

function App() {
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('refchecker-theme')
    return saved || 'system'
  })

  useEffect(() => {
    logger.debug('App', `Theme changed to: ${theme}`)
    
    // Determine the actual theme (dark or light) based on setting
    let actualTheme = theme
    if (theme === 'system') {
      actualTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    
    document.documentElement.classList.toggle('dark', actualTheme === 'dark')
    localStorage.setItem('refchecker-theme', theme)
  }, [theme])

  // Listen for system theme changes when in 'system' mode
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => {
      if (theme === 'system') {
        document.documentElement.classList.toggle('dark', mediaQuery.matches)
      }
    }
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [theme])

  const handleThemeChange = (newTheme) => {
    setTheme(newTheme)
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--color-bg-primary)' }}>
      {/* Sidebar */}
      <Sidebar />
      
      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <LiveWebSocketManager />
        {/* Header */}
        <header 
          className="h-14 flex items-center justify-between px-6 border-b"
          style={{ 
            backgroundColor: 'var(--color-bg-secondary)',
            borderColor: 'var(--color-border)'
          }}
        >
          <h1 
            className="text-xl font-semibold"
            style={{ color: 'var(--color-text-primary)' }}
          >
            RefChecker
          </h1>
        </header>
        
        {/* Main Panel */}
        <MainPanel />
      </div>

      {/* Debug Panel */}
      <DebugPanel />

      {/* Settings Panel Modal */}
      <SettingsPanel theme={theme} onThemeChange={handleThemeChange} />
    </div>
  )
}

export default App
