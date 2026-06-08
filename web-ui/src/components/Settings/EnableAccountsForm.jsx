import { useState, useEffect } from 'react'
import { getAuthConfig, setAuthConfig } from '../../utils/api'
import { isTauri, invokeTauri, openExternal } from '../../utils/tauriBridge'
import { logger } from '../../utils/logger'

const PROVIDERS = [
  { key: 'google', label: 'Google', idField: 'google_client_id', secretField: 'google_client_secret' },
  { key: 'github', label: 'GitHub', idField: 'github_client_id', secretField: 'github_client_secret' },
  { key: 'microsoft', label: 'Microsoft', idField: 'ms_client_id', secretField: 'ms_client_secret' },
]

/**
 * In-app "Enable accounts & Teams". Turns on multi-user mode + OAuth from the
 * desktop app itself: it saves the config (PUT /auth/config), which the backend
 * persists to a private app-data file the sidecar loads at startup, then
 * relaunches the app so accounts + Teams light up — no hand-editing a .env.
 *
 * Real-data only: secrets are write-only (never echoed back); the form only
 * reports WHICH providers are already configured, and never fabricates a
 * logged-in state.
 */
export default function EnableAccountsForm({ accent, repoUrl }) {
  const [cfg, setCfg] = useState(null)
  const [multiuser, setMultiuser] = useState(false)
  const [fields, setFields] = useState({})   // creds being entered (write-only)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let alive = true
    getAuthConfig()
      .then((r) => { if (alive) { setCfg(r.data); setMultiuser(!!r.data?.multiuser_configured) } })
      .catch((e) => logger.debug?.('EnableAccounts', 'config load failed', e?.response?.status))
    return () => { alive = false }
  }, [])

  const setField = (k, v) => setFields((f) => ({ ...f, [k]: v }))
  const configured = cfg?.providers || {}
  const providerReady = (p) => configured[p.key] || (fields[p.idField]?.trim() && fields[p.secretField]?.trim())
  const anyProvider = PROVIDERS.some(providerReady)

  const apply = async () => {
    setError('')
    if (multiuser && !anyProvider) { setError('Enter at least one provider’s Client ID and Secret.'); return }
    setBusy(true)
    try {
      await setAuthConfig({ multiuser, ...fields })
      setSaved(true)
      if (isTauri()) setTimeout(() => { invokeTauri('plugin:process|restart').catch(() => {}) }, 900)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Could not save the configuration.')
      setBusy(false)
    }
  }

  const fld = { background: 'var(--color-bg-primary)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }

  if (saved) {
    return (
      <div className="rounded-lg p-3 text-sm border" style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-primary)', color: 'var(--color-text-secondary)' }}>
        <strong style={{ color: 'var(--color-text-primary)' }}>Saved.</strong>{' '}
        {isTauri() ? 'Restarting the app to apply — sign-in & Teams will appear when it’s back.' : 'Restart the backend to apply; sign-in & Teams will then appear.'}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-primary)' }}>
        <input type="checkbox" checked={multiuser} onChange={(e) => setMultiuser(e.target.checked)} />
        <span className="font-medium">Enable accounts &amp; Teams (multi-user mode)</span>
      </label>
      <div className="text-xs" style={{ color: 'var(--color-text-muted, #9ca3af)' }}>
        Paste the OAuth credentials for each provider you want (you create the OAuth app in that provider’s
        console — <button type="button" onClick={() => openExternal(`${repoUrl}#multi-user--teams`)} className="underline" style={{ color: accent }}>setup guide</button>).
        Add at least one. Secrets are stored locally on this machine and never shown again.
      </div>

      {multiuser && PROVIDERS.map((p) => (
        <div key={p.key} className="rounded-md p-2.5" style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>{p.label}</span>
            {configured[p.key] && <span className="text-xs" style={{ color: 'var(--color-success, #10b981)' }}>✓ configured</span>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input className="text-sm rounded px-2 py-1.5 min-w-0" style={fld}
              placeholder={configured[p.key] ? 'Client ID (set — blank keeps it)' : `${p.label} Client ID`}
              value={fields[p.idField] || ''} onChange={(e) => setField(p.idField, e.target.value)} />
            <input type="password" className="text-sm rounded px-2 py-1.5 min-w-0" style={fld}
              placeholder={configured[p.key] ? 'Secret (set — blank keeps it)' : `${p.label} Client Secret`}
              value={fields[p.secretField] || ''} onChange={(e) => setField(p.secretField, e.target.value)} />
          </div>
        </div>
      ))}

      {error && <div className="text-xs" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</div>}

      <div className="flex items-center gap-2">
        <button type="button" onClick={apply} disabled={busy}
          className="text-sm rounded-md px-3 py-1.5 font-medium disabled:opacity-50"
          style={{ background: accent, color: '#fff' }}>
          {busy ? 'Applying…' : multiuser ? 'Apply & restart' : 'Save (keep single-user)'}
        </button>
        {cfg?.multiuser_active && <span className="text-xs" style={{ color: 'var(--color-success, #10b981)' }}>accounts currently ON</span>}
        {cfg?.needs_restart && !cfg?.multiuser_active && <span className="text-xs" style={{ color: 'var(--color-warning, #f59e0b)' }}>restart pending</span>}
      </div>
    </div>
  )
}
