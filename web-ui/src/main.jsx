import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { logger } from './utils/logger'
import { installLinkHandler, isTauri } from './utils/tauriBridge'

logger.info('App', `RefChecker Web UI starting (tauri=${isTauri()})...`)

// Intercept external link clicks so they open in the system browser when
// running inside the Tauri desktop app (the WebView ignores target=_blank).
installLinkHandler()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
