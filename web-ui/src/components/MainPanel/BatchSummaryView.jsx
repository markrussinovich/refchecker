import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'
import { openExternal } from '../../utils/tauriBridge'
import ShareModal from '../Modals/ShareModal'
import PresenceAvatars from '../Presence/PresenceAvatars'

/**
 * Batch summary view (v0.7.45) — the dedicated MainPanel page that
 * opens when the user clicks a batch row in the sidebar.
 *
 * Surfaces:
 *  - Aggregate counters across every child paper (errors, warnings,
 *    hallucinations, fabrications, unverified, verified-clean)
 *  - Total LLM budget + token spend across the batch (from the
 *    `/batch/{batch_id}/llm-usage` aggregator that v0.7.45 added)
 *  - Per-paper row list with status badge, ref count, error/halluc
 *    counts, and an Open button that drills into the standard
 *    check view (preserves selectedBatchId so the per-paper view
 *    shows "← Back to batch")
 *  - Cancel All button for in-progress batches
 *  - Auto-refresh while any child is in_progress so the user sees
 *    progress without manually reloading
 */

const STATUS_COLOR = {
  completed: '#22c55e',
  in_progress: '#3b82f6',
  error: '#ef4444',
  cancelled: '#94a3b8',
  queued: '#94a3b8',
}

function fmtUsd(n) {
  if (!n && n !== 0) return '$0.00'
  return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`
}
function fmtTok(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export default function BatchSummaryView() {
  const selectedBatch = useHistoryStore(s => s.selectedBatch)
  const isLoadingBatch = useHistoryStore(s => s.isLoadingBatch)
  const batchError = useHistoryStore(s => s.batchError)
  const selectedBatchId = useHistoryStore(s => s.selectedBatchId)
  const selectBatch = useHistoryStore(s => s.selectBatch)
  const openBatchChild = useHistoryStore(s => s.openBatchChild)
  const [usage, setUsage] = useState({ input_tokens: 0, output_tokens: 0, cost_usd: 0, by_flow: {}, per_check: {} })
  const [isCancelling, setIsCancelling] = useState(false)
  const [filter, setFilter] = useState('all') // all | error | hallucinated | in_progress | completed
  const [showShare, setShowShare] = useState(false)

  const batchId = selectedBatch?.batch_id
  const checks = selectedBatch?.checks || []

  // Per-status aggregates. Walks every child once and tallies into
  // the buckets the user asked about, including hallucination /
  // fabrication counts (refs with hallucination_assessment LIKELY).
  const agg = useMemo(() => {
    let total = 0, completed = 0, inProgress = 0, errored = 0, cancelled = 0
    let totalRefs = 0, errorsRefs = 0, warningsRefs = 0, hallucRefs = 0, unverifiedRefs = 0, verifiedRefs = 0
    let aiHigh = 0, aiMedium = 0
    for (const c of checks) {
      total += 1
      if (c.status === 'in_progress') inProgress += 1
      else if (c.status === 'completed') completed += 1
      else if (c.status === 'error') errored += 1
      else if (c.status === 'cancelled') cancelled += 1
      totalRefs += c.total_refs || 0
      errorsRefs += c.errors_count || 0
      warningsRefs += c.warnings_count || 0
      hallucRefs += c.hallucination_count || 0
      unverifiedRefs += c.unverified_count || 0
      verifiedRefs += Math.max(0, (c.total_refs || 0) - (c.errors_count || 0) - (c.warnings_count || 0) - (c.unverified_count || 0) - (c.hallucination_count || 0))
      if (c.ai_detection_band === 'high') aiHigh += 1
      else if (c.ai_detection_band === 'medium') aiMedium += 1
    }
    return { total, completed, inProgress, errored, cancelled, totalRefs, errorsRefs, warningsRefs, hallucRefs, unverifiedRefs, verifiedRefs, aiHigh, aiMedium }
  }, [checks])

  // Fetch aggregated LLM usage. Re-runs whenever the batch's progress
  // changes (so the budget chip ticks up while papers complete).
  const fetchUsage = useCallback(async () => {
    if (!batchId) return
    try {
      const resp = await api.getBatchLLMUsage(batchId)
      setUsage(resp.data || {})
    } catch (e) {
      logger.warning?.('BatchSummary', 'fetchUsage failed', e)
    }
  }, [batchId])

  useEffect(() => {
    fetchUsage()
  }, [fetchUsage, agg.completed, agg.errored, agg.cancelled])

  // v0.7.57: fan out a `refchecker:check-completed` window event
  // when a poll detects new completions. The 16-WS cap (v0.7.44)
  // means only a handful of children dispatch this themselves; for
  // 800-paper batches the SeenReferencesView library tab would never
  // refresh because 784 child completions were invisible. Now the
  // poll fires the event whenever agg.completed climbs, so the
  // library refreshes through the existing listener (no extra wiring).
  const prevCompletedRef = useRef(0)
  useEffect(() => {
    if (agg.completed > prevCompletedRef.current) {
      try {
        window.dispatchEvent(new CustomEvent('refchecker:check-completed', {
          detail: { batchId, completed: agg.completed, total: agg.total },
        }))
      } catch { /* SSR guard */ }
    }
    prevCompletedRef.current = agg.completed
  }, [agg.completed, agg.total, batchId])

  // Live refresh while any child is in_progress. Polls the batch
  // detail every 4s. WebSocket multiplex (v0.7.44 capped at 16) means
  // we can't rely on per-child WS for every paper in a 800-strong
  // batch — periodic re-fetch is the catch-all.
  useEffect(() => {
    if (!batchId || agg.inProgress === 0) return
    const id = setInterval(() => {
      selectBatch(batchId)
    }, 4000)
    return () => clearInterval(id)
  }, [batchId, agg.inProgress, selectBatch])

  const handleCancelAll = async () => {
    if (!batchId || isCancelling) return
    if (!window.confirm(`Cancel all ${agg.inProgress} in-progress papers in this batch?`)) return
    setIsCancelling(true)
    try {
      await api.cancelBatch(batchId)
      await selectBatch(batchId)
    } catch (e) {
      logger.error('BatchSummary', 'cancelBatch failed', e)
    } finally {
      setIsCancelling(false)
    }
  }

  // v0.7.47: Cancel + delete in one stroke. The user asked for this so
  // they don't have to do "cancel, wait, confirm delete, wait" when
  // they realise they grabbed the wrong folder.
  const handleCancelAndDelete = async () => {
    if (!batchId || isCancelling) return
    const confirmMsg = agg.inProgress > 0
      ? `Cancel ${agg.inProgress} in-progress AND delete all ${agg.total} papers in this batch? This can't be undone.`
      : `Delete all ${agg.total} papers in this batch? This can't be undone.`
    if (!window.confirm(confirmMsg)) return
    setIsCancelling(true)
    try {
      if (agg.inProgress > 0) {
        try { await api.cancelBatch(batchId) } catch (e) { logger.warning?.('BatchSummary', 'cancelBatch failed', e) }
        await new Promise(r => setTimeout(r, 300))
      }
      // Deleting one-by-one is fine here; even 800 DELETE rows is
      // milliseconds with the timestamp index added in v0.7.46.
      for (const c of checks) {
        try { await api.deleteCheck(c.id) } catch (e) { logger.warning?.('BatchSummary', `delete ${c.id} failed`, e) }
      }
      useHistoryStore.getState().clearSelection()
      useHistoryStore.getState().fetchHistory?.()
    } catch (e) {
      logger.error('BatchSummary', 'cancel+delete failed', e)
    } finally {
      setIsCancelling(false)
    }
  }

  const filteredChecks = useMemo(() => {
    if (filter === 'all') return checks
    return checks.filter(c => {
      if (filter === 'in_progress') return c.status === 'in_progress'
      if (filter === 'completed') return c.status === 'completed'
      if (filter === 'error') return (c.errors_count || 0) > 0 || c.status === 'error'
      if (filter === 'warning') return (c.warnings_count || 0) > 0
      if (filter === 'unverified') return (c.unverified_count || 0) > 0
      if (filter === 'hallucinated') return (c.hallucination_count || 0) > 0
      if (filter === 'ai_flagged') return c.ai_detection_band === 'high' || c.ai_detection_band === 'medium'
      return true
    })
  }, [checks, filter])

  if (isLoadingBatch && !selectedBatch) {
    return (
      <div className="p-6 text-center text-sm flex flex-col items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
        <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Loading batch…
      </div>
    )
  }
  // Error/timeout escape hatch — previously this returned null, leaving the
  // user on an indefinite "Loading batch…" (if the request hung) or a blank
  // panel (if it failed). Now a failed/timed-out load is recoverable.
  if (!selectedBatch && batchError) {
    return (
      <div className="p-6 text-center text-sm flex flex-col items-center gap-3" style={{ color: 'var(--color-text-secondary)' }}>
        <svg className="w-10 h-10 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p style={{ color: 'var(--color-text-primary)' }}>Couldn’t load this batch</p>
        <p className="text-xs max-w-xs">{batchError}</p>
        <button
          type="button"
          onClick={() => selectedBatchId && selectBatch(selectedBatchId)}
          className="px-3 py-1.5 rounded-md border text-xs transition-all"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', background: 'var(--color-bg-tertiary)' }}
        >
          Retry
        </button>
      </div>
    )
  }
  if (!selectedBatch) return null

  const Chip = ({ label, value, color, active, onClick, title }) => (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="px-3 py-1.5 rounded-md border text-xs transition-all"
      style={{
        borderColor: active ? color : 'var(--color-border)',
        background: active ? `${color}22` : 'var(--color-bg-secondary)',
        color: active ? color : 'var(--color-text-primary)',
        cursor: onClick ? 'pointer' : 'default',
        fontWeight: active ? 600 : 500,
      }}
    >
      <span style={{ color }}>{label}</span>
      <span className="ml-2 font-mono" style={{ color: active ? color : 'var(--color-text-primary)' }}>{value}</span>
    </button>
  )

  return (
    <div className="space-y-3">
      {/* Header card */}
      <div className="p-3 rounded-lg border" style={{
        borderColor: 'var(--color-border)',
        backgroundColor: 'var(--color-bg-secondary)',
      }}>
        <div className="flex items-start gap-3 flex-wrap">
          <div className="text-2xl" aria-hidden="true">📦</div>
          <div className="flex-1 min-w-0">
            <div className="text-base font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {selectedBatch.batch_label || `Batch of ${agg.total} ${agg.total === 1 ? 'paper' : 'papers'}`}
            </div>
            <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              {agg.completed}/{agg.total} completed
              {agg.inProgress > 0 && <span style={{ color: STATUS_COLOR.in_progress }}> · {agg.inProgress} in progress</span>}
              {agg.errored > 0 && <span style={{ color: STATUS_COLOR.error }}> · {agg.errored} error{agg.errored === 1 ? '' : 's'}</span>}
              {agg.cancelled > 0 && <span style={{ color: STATUS_COLOR.cancelled }}> · {agg.cancelled} cancelled</span>}
            </div>
          </div>
          {/* Realtime presence — team members viewing this same batch (#67) */}
          {batchId && <PresenceAvatars roomId={`batch-${batchId}`} />}
          {agg.completed > 0 && (
            <button
              onClick={() => setShowShare(true)}
              className="px-3 py-1 rounded text-xs font-semibold inline-flex items-center gap-1.5"
              style={{ background: 'var(--color-accent)', color: '#fff', border: 'none' }}
              type="button"
              title="Export one report for this batch — overview plus each paper (HTML, PDF, Markdown or Word)"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
                <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" /><line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
              </svg>
              Share batch
            </button>
          )}
          {agg.inProgress > 0 && (
            <button
              onClick={handleCancelAll}
              disabled={isCancelling}
              className="px-3 py-1 rounded text-xs font-medium border"
              style={{
                backgroundColor: 'var(--color-error-bg, rgba(239,68,68,0.1))',
                color: 'var(--color-error, #ef4444)',
                borderColor: 'var(--color-error, #ef4444)',
                opacity: isCancelling ? 0.5 : 1,
              }}
              type="button"
              title="Stop the in-progress papers. Completed checks stay."
            >
              {isCancelling ? 'Cancelling…' : `Cancel all (${agg.inProgress})`}
            </button>
          )}
          <button
            onClick={handleCancelAndDelete}
            disabled={isCancelling}
            className="px-3 py-1 rounded text-xs font-medium border"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              color: 'var(--color-error, #ef4444)',
              borderColor: 'var(--color-error, #ef4444)',
              opacity: isCancelling ? 0.5 : 1,
            }}
            type="button"
            title={agg.inProgress > 0
              ? 'Cancel any in-progress AND delete every paper in this batch from history.'
              : 'Delete every paper in this batch from history.'}
          >
            {isCancelling ? '…' : (agg.inProgress > 0 ? 'Cancel & delete all' : 'Delete all')}
          </button>
        </div>

        {/* Aggregate counter chips */}
        <div className="flex flex-wrap gap-2 mt-3">
          <Chip label="Total refs" value={agg.totalRefs} color="var(--color-text-secondary)" />
          <Chip
            label="Verified clean"
            value={agg.verifiedRefs}
            color="#22c55e"
            active={filter === 'completed'}
            onClick={() => setFilter(f => f === 'completed' ? 'all' : 'completed')}
            title="Click to show only fully-clean papers"
          />
          <Chip
            label="Errors"
            value={agg.errorsRefs}
            color="#ef4444"
            active={filter === 'error'}
            onClick={() => setFilter(f => f === 'error' ? 'all' : 'error')}
            title="Click to filter to papers with errors / fabricated refs"
          />
          <Chip
            label="Warnings"
            value={agg.warningsRefs}
            color="#f59e0b"
            active={filter === 'warning'}
            onClick={() => setFilter(f => f === 'warning' ? 'all' : 'warning')}
            title="Click to filter to papers with style-aware warnings (NLM venue abbreviations, author-order diffs, etc.)"
          />
          <Chip
            label="Hallucinated"
            value={agg.hallucRefs}
            color="#a855f7"
            active={filter === 'hallucinated'}
            onClick={() => setFilter(f => f === 'hallucinated' ? 'all' : 'hallucinated')}
            title="Click to filter to papers with LIKELY-hallucinated refs"
          />
          <Chip
            label="Unverified"
            value={agg.unverifiedRefs}
            color="#94a3b8"
            active={filter === 'unverified'}
            onClick={() => setFilter(f => f === 'unverified' ? 'all' : 'unverified')}
            title="Click to filter to papers with refs the verifier couldn't resolve (no S2/Crossref/PMC hit + LLM didn't flag as hallucination)"
          />
          {(agg.aiHigh + agg.aiMedium) > 0 && (
            <Chip
              label="AI-flagged"
              value={agg.aiHigh + agg.aiMedium}
              color="#ef4444"
              active={filter === 'ai_flagged'}
              onClick={() => setFilter(f => f === 'ai_flagged' ? 'all' : 'ai_flagged')}
              title="Click to filter to papers whose body text scored medium/high AI-likelihood (advisory only — not proof of AI authorship)"
            />
          )}
        </div>

        {/* Budget chip + per-flow breakdown.
            v0.7.57: when the LLM-call count is much smaller than the
            batch size, the difference is explained — most papers were
            short-circuited via Crossref-by-DOI (added in v0.7.54), so
            their references arrived from Crossref's `reference` field
            with zero token cost. The hover title spells it out. */}
        {(() => {
          const llmCalls = usage.calls || 0
          const totalPapers = agg.total || 0
          const crossrefShortCircuits = Math.max(0, totalPapers - llmCalls)
          const explainsCheap = totalPapers > 0 && crossrefShortCircuits >= totalPapers * 0.5
          return (
            <div
              className="flex flex-wrap items-center gap-3 mt-3 px-3 py-2 rounded-md text-xs"
              style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
              title={explainsCheap
                ? `${crossrefShortCircuits}/${totalPapers} papers resolved via Crossref by DOI — no LLM tokens needed. Only the ${llmCalls} paper(s) without a usable DOI required LLM extraction.`
                : `LLM cost broken down by flow: extract = bibliography parsing; verify = per-ref disambiguation; hallucination = LLM-flagged refs; suggest = Similar Papers / Suggest Alternative; reverify = Apply Fix re-runs.`}
            >
              <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                💰 {fmtUsd(usage.cost_usd)}
              </span>
              <span>{fmtTok((usage.input_tokens || 0) + (usage.output_tokens || 0))} tokens</span>
              <span>{llmCalls} LLM calls</span>
              {explainsCheap && (
                <span style={{ color: '#22c55e', fontWeight: 500 }}>
                  · {crossrefShortCircuits} via Crossref (no cost)
                </span>
              )}
              {Object.keys(usage.by_flow || {}).length > 0 && (
                <span style={{ color: 'var(--color-text-muted)' }}>·</span>
              )}
              {Object.entries(usage.by_flow || {}).slice(0, 6).map(([flow, sub]) => (
                <span key={flow} style={{ color: 'var(--color-text-muted)' }}>
                  {flow}: {fmtUsd(sub.cost_usd)}
                </span>
              ))}
            </div>
          )
        })()}
      </div>

      {/* Papers list */}
      <div className="rounded-lg border overflow-hidden" style={{
        borderColor: 'var(--color-border)',
        backgroundColor: 'var(--color-bg-secondary)',
      }}>
        <div
          className="px-3 py-2 text-xs flex items-center justify-between"
          style={{
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
            borderBottom: '1px solid var(--color-border)',
          }}
        >
          <span>
            Showing {filteredChecks.length} of {checks.length} paper{checks.length === 1 ? '' : 's'}
            {filter !== 'all' && <span> · filter: {filter}</span>}
          </span>
          {filter !== 'all' && (
            <button
              onClick={() => setFilter('all')}
              className="underline"
              style={{ color: 'var(--color-accent, #3b82f6)' }}
            >
              Clear filter
            </button>
          )}
        </div>
        <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
          {filteredChecks.map(c => {
            const isVerifiedClean = (c.errors_count || 0) === 0 && (c.warnings_count || 0) === 0 && (c.hallucination_count || 0) === 0 && (c.unverified_count || 0) === 0 && c.status === 'completed'
            const hasHallu = (c.hallucination_count || 0) > 0
            const checkCost = usage.per_check?.[c.id]?.cost_usd
            return (
              <div
                key={c.id}
                className="px-3 py-2 flex items-center gap-3 border-b"
                style={{ borderColor: 'var(--color-border)' }}
              >
                {/* Status dot */}
                <span
                  className="inline-block rounded-full flex-shrink-0"
                  style={{
                    width: 8, height: 8,
                    background: hasHallu ? '#a855f7' : (STATUS_COLOR[c.status] || '#94a3b8'),
                  }}
                  title={hasHallu ? 'Has likely-hallucinated refs' : c.status}
                />
                {/* Title */}
                <div className="flex-1 min-w-0">
                  <div
                    className="text-sm truncate"
                    style={{ color: 'var(--color-text-primary)' }}
                    title={c.paper_title || c.paper_source}
                  >
                    {c.paper_title || c.paper_source || `Check #${c.id}`}
                  </div>
                  <div className="text-xs mt-0.5 flex flex-wrap gap-2" style={{ color: 'var(--color-text-secondary)' }}>
                    {c.status === 'in_progress' && <span style={{ color: STATUS_COLOR.in_progress }}>checking…</span>}
                    {(c.total_refs || 0) > 0 && <span>{c.total_refs} ref{c.total_refs === 1 ? '' : 's'}</span>}
                    {(c.errors_count || 0) > 0 && <span style={{ color: '#ef4444' }}>{c.errors_count} err</span>}
                    {(c.warnings_count || 0) > 0 && <span style={{ color: '#f59e0b' }}>{c.warnings_count} warn</span>}
                    {hasHallu && <span style={{ color: '#a855f7' }}>{c.hallucination_count} halluc</span>}
                    {(c.unverified_count || 0) > 0 && <span style={{ color: '#94a3b8' }}>{c.unverified_count} unv</span>}
                    {(c.ai_detection_band === 'high' || c.ai_detection_band === 'medium') && (
                      <span style={{ color: c.ai_detection_band === 'high' ? '#ef4444' : '#f59e0b' }}
                        title="AI-generated-text likelihood (advisory, not proof)">
                        AI {c.ai_detection_band}
                      </span>
                    )}
                    {isVerifiedClean && <span style={{ color: '#22c55e' }}>✓ clean</span>}
                    {checkCost ? <span style={{ color: 'var(--color-text-muted)' }}>· {fmtUsd(checkCost)}</span> : null}
                  </div>
                </div>
                {/* External view + Open buttons (v0.7.57). The
                    external link only appears when paper_source is an
                    http(s) URL — for file/text uploads there's nothing
                    to point at. */}
                {typeof c.paper_source === 'string' && /^https?:\/\//.test(c.paper_source) && (
                  <button
                    onClick={() => openExternal(c.paper_source)}
                    className="text-xs px-2 py-1 rounded border flex-shrink-0"
                    style={{
                      background: 'var(--color-bg-primary)',
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-secondary)',
                    }}
                    title={`Open source URL in browser: ${c.paper_source}`}
                  >
                    ↗ Source
                  </button>
                )}
                <button
                  onClick={() => openBatchChild(c.id)}
                  className="text-xs px-3 py-1 rounded border flex-shrink-0"
                  style={{
                    background: 'var(--color-bg-primary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                  disabled={c.status === 'in_progress' && (c.total_refs || 0) === 0}
                  title="Open this paper's standard check view (back navigation preserved)"
                >
                  Open →
                </button>
              </div>
            )
          })}
          {filteredChecks.length === 0 && (
            <div className="p-6 text-center text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              No papers match this filter.
            </div>
          )}
        </div>
      </div>
      {showShare && (
        <ShareModal
          batchId={batchId}
          title={selectedBatch.batch_label || `Batch of ${agg.total} ${agg.total === 1 ? 'paper' : 'papers'}`}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  )
}
