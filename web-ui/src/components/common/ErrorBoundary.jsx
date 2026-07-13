import { Component } from 'react'
import { logger } from '../../utils/logger'

/**
 * App-level error boundary. A render-time crash in any component (a
 * rules-of-hooks violation, a malformed API payload, etc.) used to unmount the
 * entire React tree and leave a blank window. This catches it, shows a
 * recoverable fallback instead, and records the error for the diagnostics
 * report — so one bad render can never blank the whole app again.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    logger.error('ErrorBoundary', 'Render error caught', error?.message || error, info?.componentStack)
  }

  handleReset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    const card = {
      maxWidth: 460, textAlign: 'center', padding: 24, borderRadius: 12,
      background: 'var(--color-bg-secondary, #161b22)', border: '1px solid var(--color-border, #30363d)',
    }
    const btn = {
      padding: '8px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
    }
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        background: 'var(--color-bg-primary, #0d1117)', color: 'var(--color-text-primary, #e6edf3)',
      }}>
        <div style={card}>
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 8 }}>Something went wrong</div>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted, #8b949e)', lineHeight: 1.5, marginBottom: 16 }}>
            A part of the app hit an unexpected error. Your checks are saved — try again, or reload the window.
          </p>
          <pre style={{
            fontSize: 11, textAlign: 'left', overflow: 'auto', maxHeight: 120, padding: 8, borderRadius: 8,
            background: 'var(--color-bg-primary, #0d1117)', border: '1px solid var(--color-border, #30363d)',
            color: 'var(--color-error, #ef4444)', marginBottom: 16, whiteSpace: 'pre-wrap',
          }}>{String(this.state.error?.message || this.state.error)}</pre>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            <button type="button" onClick={this.handleReset}
              style={{ ...btn, background: 'var(--color-accent, #10b981)', color: '#fff', border: 'none' }}>
              Try again
            </button>
            <button type="button" onClick={() => window.location.reload()}
              style={{ ...btn, background: 'transparent', color: 'var(--color-text-secondary, #c9d1d9)', border: '1px solid var(--color-border, #30363d)' }}>
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
