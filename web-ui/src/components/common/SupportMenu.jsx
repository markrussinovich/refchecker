import { useState, useRef, useEffect } from 'react'
import { isTauri, openExternal } from '../../utils/tauriBridge'

const REPO_URL = 'https://github.com/ArioMoniri/refchecker'
const SUPPORT_EMAILS = ['ariorad.moniri@live.acibadem.edu.tr', 'mark.russinovich@microsoft.com']

/**
 * Help & support menu in the header: open a GitHub issue or email the
 * maintainers. Mirrors UserMenu's outside-click-close pattern; external links
 * go through openExternal in the Tauri desktop shell (mailto included).
 */
export default function SupportMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const go = (url, isMailto = false) => {
    setOpen(false)
    if (isTauri()) { openExternal(url); return }
    if (isMailto) { window.location.href = url } else { window.open(url, '_blank', 'noopener,noreferrer') }
  }
  const githubIssue = () => go(`${REPO_URL}/issues/new`)
  const emailSupport = () => go(`mailto:${SUPPORT_EMAILS.join(',')}?subject=${encodeURIComponent('RefChecker support')}`, true)

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="text-gray-400 hover:text-gray-200 transition-colors flex items-center"
        aria-label="Help & support" title="Help & support">
        <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-56 rounded-lg shadow-lg z-50 py-1"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="px-3 py-1.5 text-xs font-semibold" style={{ color: 'var(--color-text-muted)' }}>Help &amp; support</div>
          <button type="button" onClick={githubIssue}
            className="w-full text-left px-3 py-2 text-sm hover:opacity-80 flex items-center gap-2"
            style={{ color: 'var(--color-text-primary)' }}>
            <svg className="w-4 h-4 flex-none" fill="currentColor" viewBox="0 0 24 24"><path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" /></svg>
            Open a GitHub issue
          </button>
          <button type="button" onClick={emailSupport}
            className="w-full text-left px-3 py-2 text-sm hover:opacity-80 flex items-center gap-2"
            style={{ color: 'var(--color-text-primary)' }}>
            <svg className="w-4 h-4 flex-none" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2" /><path strokeLinecap="round" strokeLinejoin="round" d="M22 7l-10 6L2 7" /></svg>
            Email support
          </button>
        </div>
      )}
    </div>
  )
}
