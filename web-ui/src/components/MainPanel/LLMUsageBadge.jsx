import { useEffect, useState, useMemo, useRef } from 'react'
import { getLLMUsage } from '../../utils/api'

/**
 * Per-check LLM token + cost chip for the Summary header.
 *
 *   `LLM 2.4K tok $0.015`
 *
 * Resets to 0 on every new check_id (controlled by the backend
 * accumulator that fires `usage_tracker.reset(check_id)` at the top of
 * each `check_paper`). Hover surfaces a breakdown by flow
 * (extract / verify / hallucination / suggest / graph / reverify) plus a
 * by-model split when the cascade used more than one provider.
 *
 * Polls every ~3s while the check is in progress so the badge ticks up
 * live, then drops back to occasional refreshes after completion to pick
 * up costs from re-verify / suggest / graph follow-ups.
 */

const FLOW_LABEL = {
  extract: 'Reference extraction',
  verify: 'Reference verification',
  hallucination: 'Hallucination check',
  suggest: 'Suggested alternatives',
  graph: 'Citation graph',
  reverify: 'Re-verify',
  context: 'Inline citation contexts',
  ai_detection: 'AI-generated-text detection',
  other: 'Other LLM calls',
}

function fmtTokens(n) {
  if (!n || n < 1000) return `${n || 0}`
  if (n < 10_000) return `${(n / 1000).toFixed(1)}K`
  if (n < 1_000_000) return `${Math.round(n / 1000)}K`
  return `${(n / 1_000_000).toFixed(1)}M`
}

function fmtCost(c) {
  if (!c) return '$0.000'
  if (c < 0.01) return `$${c.toFixed(4)}`
  if (c < 1) return `$${c.toFixed(3)}`
  if (c < 10) return `$${c.toFixed(2)}`
  return `$${c.toFixed(1)}`
}

export default function LLMUsageBadge({ checkId, isComplete }) {
  const [usage, setUsage] = useState(null)
  const [showHover, setShowHover] = useState(false)
  const lastFetchRef = useRef(0)

  useEffect(() => {
    if (!checkId || checkId === -1) {
      setUsage(null)
      return undefined
    }
    let cancelled = false
    const fetchUsage = async () => {
      try {
        const res = await getLLMUsage(checkId)
        if (cancelled) return
        setUsage(res?.data || null)
        lastFetchRef.current = Date.now()
      } catch {
        // Best-effort; the badge stays at its last good value.
      }
    }
    fetchUsage()
    // While the check is running, poll fast so the number ticks up
    // live like a graph. Once complete, slow down to catch occasional
    // re-verify / suggest spend without hammering. v0.7.62: dropped the
    // running interval from 3s → 1.5s after users reported the badge
    // didn't feel real-time, and bumped the complete interval from 15s
    // → 8s so re-verify cost lands on the chip quickly.
    const interval = isComplete ? 8_000 : 1_500
    const id = setInterval(fetchUsage, interval)
    // Refresh IMMEDIATELY when an edit spends tokens (apply-fix / restore /
    // re-verify) instead of waiting up to 8s for the next poll — that delay is
    // why the badge "doesn't update" after the user applies a correction.
    window.addEventListener('refchecker:usage-changed', fetchUsage)
    return () => {
      cancelled = true
      clearInterval(id)
      window.removeEventListener('refchecker:usage-changed', fetchUsage)
    }
  }, [checkId, isComplete])

  const totalTokens = useMemo(() => {
    if (!usage) return 0
    return (usage.input_tokens || 0) + (usage.output_tokens || 0)
  }, [usage])

  if (!checkId || checkId === -1) return null
  // v0.7.62: Always render the badge when a check is in scope, even at
  // 0 tokens. The old code returned null whenever totalTokens===0, so
  // Crossref-short-circuited papers opened from the Batch view showed
  // no badge at all (users assumed "the tracker isn't working"). Now
  // the badge always shows so the user can see the live counter and,
  // for cheap papers, the explicit "0 LLM calls" state.

  const flowEntries = Object.entries(usage?.by_flow || {})
    .filter(([, v]) => (v.input_tokens || 0) + (v.output_tokens || 0) > 0)
    .sort((a, b) => (b[1].cost_usd || 0) - (a[1].cost_usd || 0))

  const modelEntries = Object.entries(usage?.by_model || {})
    .filter(([, v]) => (v.input_tokens || 0) + (v.output_tokens || 0) > 0)
    .sort((a, b) => (b[1].cost_usd || 0) - (a[1].cost_usd || 0))

  return (
    <span
      className="relative inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-primary)',
        cursor: 'help',
      }}
      onMouseEnter={() => setShowHover(true)}
      onMouseLeave={() => setShowHover(false)}
    >
      <span style={{ color: 'var(--color-text-secondary)' }}>LLM</span>
      <span>{fmtTokens(totalTokens)} tok</span>
      <span style={{ color: 'var(--color-success, #10b981)', fontWeight: 700 }}>
        {fmtCost(usage?.cost_usd || 0)}
      </span>
      {/* Live tick indicator while polling — fades when complete. */}
      {!isComplete && (
        <span
          aria-hidden
          className="inline-block w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ background: 'var(--color-success, #10b981)' }}
        />
      )}

      {showHover && (
        <div
          className="absolute top-full left-0 mt-1 z-50 rounded-md shadow-lg p-3 text-xs"
          style={{
            background: 'var(--color-bg-primary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-primary)',
            minWidth: 240,
            maxWidth: 320,
            cursor: 'default',
          }}
        >
          <div style={{ color: 'var(--color-text-secondary)', marginBottom: 6 }}>
            {totalTokens === 0 ? (
              isComplete ? (
                <>This check used <strong>0</strong> LLM tokens — every reference was resolved deterministically (Crossref / arXiv / Semantic Scholar) without paid LLM calls.</>
              ) : (
                <>Waiting for the first LLM call to land. The badge ticks live as extraction / verification / hallucination flows record usage.</>
              )
            ) : (
              <>This check used <strong>{fmtTokens(totalTokens)}</strong> tokens
              ({fmtTokens(usage?.input_tokens || 0)} in / {fmtTokens(usage?.output_tokens || 0)} out)
              across <strong>{usage?.calls || 0}</strong> LLM call{usage?.calls === 1 ? '' : 's'}.</>
            )}
          </div>
          {flowEntries.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ color: 'var(--color-text-secondary)', marginBottom: 2 }}>
                By flow
              </div>
              {flowEntries.map(([flow, v]) => (
                <div key={flow} className="flex items-center justify-between gap-3">
                  <span>{FLOW_LABEL[flow] || flow}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    {fmtTokens((v.input_tokens || 0) + (v.output_tokens || 0))}
                    {' · '}
                    <span style={{ color: 'var(--color-success, #10b981)' }}>{fmtCost(v.cost_usd || 0)}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
          {modelEntries.length > 1 && (
            <div>
              <div style={{ color: 'var(--color-text-secondary)', marginBottom: 2 }}>
                By model
              </div>
              {modelEntries.map(([model, v]) => (
                <div key={model} className="flex items-center justify-between gap-3">
                  <span style={{ wordBreak: 'break-all' }}>{model}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>{fmtCost(v.cost_usd || 0)}</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ color: 'var(--color-text-muted)', marginTop: 6, fontSize: 10 }}>
            Resets at the start of each new check. Cost is an estimate based on published per-million token rates.
          </div>
        </div>
      )}
    </span>
  )
}
