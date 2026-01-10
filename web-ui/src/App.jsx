import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar/Sidebar'
import MainPanel from './components/MainPanel/MainPanel'
import ThemeToggle from './components/common/ThemeToggle'
import DebugPanel from './components/DebugPanel'
import LiveWebSocketManager from './components/LiveWebSocketManager'
import { logger } from './utils/logger'

function App() {
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem('refchecker-theme')
    return saved || 'light'
  })

  useEffect(() => {
    logger.debug('App', `Theme changed to: ${theme}`)
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('refchecker-theme', theme)
  }, [theme])

  const toggleTheme = () => {
    setTheme(prev => prev === 'light' ? 'dark' : 'light')
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
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </header>
        
        {/* Main Panel */}
        <MainPanel />
      </div>

      {/* Debug Panel */}
      <DebugPanel />
    </div>
  )
}

export default App
