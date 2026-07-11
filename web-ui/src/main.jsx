import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/common/ErrorBoundary.jsx'
import { logger } from './utils/logger'
import { installLinkHandler, isTauri } from './utils/tauriBridge'
import { installDiagnosticsRecorder } from './utils/diagnostics'

logger.info('App', `RefChecker Web UI starting (tauri=${isTauri()})...`)

// Intercept external link clicks so they open in the system browser when
// running inside the Tauri desktop app (the WebView ignores target=_blank).
installLinkHandler()

// Wrap console.warn/error and capture unhandled rejections so Settings →
// Diagnostics can attach the last ~200 log lines to a bug report.
installDiagnosticsRecorder()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
