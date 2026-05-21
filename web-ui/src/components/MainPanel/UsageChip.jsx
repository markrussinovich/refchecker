import { useEffect, useState } from 'react'
import { fetchUsageTotals, resetUsageTotals } from '../../utils/api'

/**
 * Minimal chip that surfaces per-provider LLM token + cost totals.
 *
 * Sits in the Summary header next to the citation-health chip. Polls
 * /api/usage/totals after every check (via the same
 * `refchecker:check-completed` window event), and on mount. Hover for
 * per-provider breakdown.
 */
function fmtUsd(n) {
  if (n == null) return null
  if (n === 0) return '$0'
  if (n < 0.01) return '<$0.01'
  return `$${n.toFixed(n < 1 ? 3 : 2)}`
}

function fmtTokens(n) {
  if (n == null) return '0'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`
  return `${(n / 1_000_000).toFixed(2)}M`
}

export default function UsageChip() {
  const [snap, setSnap] = useState(null)

  const reload = async () => {
    try {
      const res = await fetchUsageTotals()
      setSnap(res.data)
    } catch {
      setSnap(null)
    }
  }

  useEffect(() => {
    reload()
    const onCheckDone = () => reload()
    window.addEventListener('refchecker:check-completed', onCheckDone)
    return () => window.removeEventListener('refchecker:check-completed', onCheckDone)
  }, [])

  if (!snap || !snap.totals || snap.totals.calls === 0) return null

  const { totals, providers = [] } = snap
  const tokens = (totals.input_tokens || 0) + (totals.output_tokens || 0)
  const cost = fmtUsd(totals.cost_usd)
  const tooltip = providers.map(p => {
    const total = (p.input_tokens || 0) + (p.output_tokens || 0)
    const c = fmtUsd(p.cost_usd)
    return `${p.provider}/${p.model}: ${fmtTokens(total)} tokens${c ? ` · ${c}` : ' · cost unknown'} (${p.calls} calls)`
  }).join('\n')

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-secondary)',
      }}
    >
      <span style={{ opacity: 0.7 }}>LLM</span>
      <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>{fmtTokens(tokens)}</span>
      <span style={{ opacity: 0.7 }}>tok</span>
      {cost && <span style={{ color: 'var(--color-accent, #3b82f6)', fontWeight: 600 }}>{cost}</span>}
    </span>
  )
}
