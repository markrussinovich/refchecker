import { useEffect, useState } from 'react'
import { useConfigStore } from '../../stores/useConfigStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { openExternal, isTauri } from '../../utils/tauriBridge'

/**
 * First-launch guidance for the desktop app.
 *
 * Shown above the input section when:
 *  - the user hasn't dismissed it in this browser, AND
 *  - they're either missing an LLM config OR have no local database
 *    directory configured (the two things that meaningfully change what
 *    RefChecker can do).
 *
 * Dismissed state persists per-browser via localStorage.
 */
const DISMISS_KEY = 'refchecker.onboarding.dismissed.v1'

export default function OnboardingBanner({ onOpenSettings }) {
  const configs = useConfigStore(s => s.configs)
  const settings = useSettingsStore(s => s.settings)
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISS_KEY) === '1' } catch { return false }
  })

  // Refetch settings the first time we render so the offline-DB hint
  // doesn't show during the initial paint when settings are still null.
  const fetchSettings = useSettingsStore(s => s.fetchSettings)
  useEffect(() => { fetchSettings?.() }, [fetchSettings])

  if (dismissed) return null

  const hasLlm = Array.isArray(configs) && configs.some(c => c.has_key || c.id)
  const dbPathSet = !!settings?.db_path?.value
  const allDone = hasLlm && dbPathSet
  if (allDone) return null

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, '1') } catch {}
    setDismissed(true)
  }

  return (
    <div
      className="rounded-lg border p-4 mb-4"
      style={{
        borderColor: 'var(--color-accent, #3b82f6)',
        backgroundColor: 'rgba(59,130,246,0.06)',
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
            Welcome to RefChecker Desktop
          </div>
          <p className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
            Two quick things will make it noticeably faster and more accurate.
            Both are optional — you can paste an ArXiv ID right now and it'll work
            out of the box using public APIs.
          </p>

          <ol className="space-y-3 text-sm" style={{ color: 'var(--color-text-primary)' }}>
            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: hasLlm ? 'var(--color-success, #22c55e)' : 'var(--color-accent, #3b82f6)',
                  color: 'white',
                }}
              >
                {hasLlm ? '✓' : '1'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  Add an LLM API key {hasLlm && <span style={{ color: 'var(--color-success, #22c55e)' }}>— configured</span>}
                </div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Needed for accurate bibliography parsing and for the hallucination check.
                  OpenAI, Anthropic, Google, Azure, or a local vLLM server are supported.
                  Open <button type="button" onClick={() => onOpenSettings?.('LLM')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → LLM</button>{' '}
                  to paste your key — click <b>Test connection</b> first, then Save.
                </div>
              </div>
            </li>

            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: dbPathSet ? 'var(--color-success, #22c55e)' : 'var(--color-accent, #3b82f6)',
                  color: 'white',
                }}
              >
                {dbPathSet ? '✓' : '2'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  (Optional) Download the offline database pack {dbPathSet && <span style={{ color: 'var(--color-success, #22c55e)' }}>— directory configured</span>}
                </div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Speeds up verification 5–10× and lets you check papers without an internet round-trip.
                  Open <button type="button" onClick={() => onOpenSettings?.('General')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → General</button>,
                  click <b>Use default</b> next to <i>Local Database Directory</i>, then{' '}
                  <b>Build local databases</b> below it (Semantic Scholar, DBLP, OpenAlex).
                </div>
              </div>
            </li>

            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: 'var(--color-text-muted, #94a3b8)',
                  color: 'white',
                }}
              >
                i
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">Bonus: Semantic Scholar API key</div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Cuts verification time from 5–10s to 1–2s per reference.
                  Free key at{' '}
                  <button
                    type="button"
                    onClick={() => openExternal('https://www.semanticscholar.org/product/api')}
                    className="underline"
                    style={{ color: 'var(--color-accent, #3b82f6)' }}
                  >
                    semanticscholar.org/product/api
                  </button>
                  {' '}— paste it into <button type="button" onClick={() => onOpenSettings?.('API Keys')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → API Keys</button>.
                </div>
              </div>
            </li>
          </ol>
        </div>

        <button
          type="button"
          onClick={dismiss}
          className="text-xs px-2 py-1 rounded border"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
          title="Hide this banner (re-show by clearing site data)"
        >
          Dismiss
        </button>
      </div>
      {isTauri() && (
        <div className="mt-3 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          Tip: keys live in the encrypted local DB, never on a server. Updates are checked on every launch (Settings → App updates).
        </div>
      )}
    </div>
  )
}
