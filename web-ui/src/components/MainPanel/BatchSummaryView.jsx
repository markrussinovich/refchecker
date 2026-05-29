import { useEffect, useMemo, useState, useCallback } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

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
  const selectBatch = useHistoryStore(s => s.selectBatch)
  const openBatchChild = useHistoryStore(s => s.openBatchChild)
  const [usage, setUsage] = useState({ input_tokens: 0, output_tokens: 0, cost_usd: 0, by_flow: {}, per_check: {} })
  const [isCancelling, setIsCancelling] = useState(false)
  const [filter, setFilter] = useState('all') // all | error | hallucinated | in_progress | completed

  const batchId = selectedBatch?.batch_id
  const checks = selectedBatch?.checks || []

  // Per-status aggregates. Walks every child once and tallies into
  // the buckets the user asked about, including hallucination /
  // fabrication counts (refs with hallucination_assessment LIKELY).
  const agg = useMemo(() => {
    let total = 0, completed = 0, inProgress = 0, errored = 0, cancelled = 0
    let totalRefs = 0, errorsRefs = 0, warningsRefs = 0, hallucRefs = 0, unverifiedRefs = 0, verifiedRefs = 0
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
    }
    return { total, completed, inProgress, errored, cancelled, totalRefs, errorsRefs, warningsRefs, hallucRefs, unverifiedRefs, verifiedRefs }
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
    if (!window.confirm(`Cancel ${agg.inProgress} in-progress AND delete all ${agg.total} papers in this batch? This can't be undone.`)) return
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
      if (filter === 'hallucinated') return (c.hallucination_count || 0) > 0
      return true
    })
  }, [checks, filter])

  if (isLoadingBatch && !selectedBatch) {
    return (
      <div className="p-6 text-center text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        Loading batch…
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
            title="Cancel any in-progress AND delete every paper in this batch from history."
          >
            {isCancelling ? '…' : 'Cancel & delete all'}
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
          <Chip label="Warnings" value={agg.warningsRefs} color="#f59e0b" />
          <Chip
            label="Hallucinated"
            value={agg.hallucRefs}
            color="#a855f7"
            active={filter === 'hallucinated'}
            onClick={() => setFilter(f => f === 'hallucinated' ? 'all' : 'hallucinated')}
            title="Click to filter to papers with LIKELY-hallucinated refs"
          />
          <Chip label="Unverified" value={agg.unverifiedRefs} color="#94a3b8" />
        </div>

        {/* Budget chip + per-flow breakdown */}
        <div
          className="flex flex-wrap items-center gap-3 mt-3 px-3 py-2 rounded-md text-xs"
          style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
        >
          <span style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
            💰 {fmtUsd(usage.cost_usd)}
          </span>
          <span>{fmtTok((usage.input_tokens || 0) + (usage.output_tokens || 0))} tokens</span>
          <span>{usage.calls || 0} LLM calls</span>
          {Object.keys(usage.by_flow || {}).length > 0 && (
            <span style={{ color: 'var(--color-text-muted)' }}>·</span>
          )}
          {Object.entries(usage.by_flow || {}).slice(0, 6).map(([flow, sub]) => (
            <span key={flow} style={{ color: 'var(--color-text-muted)' }}>
              {flow}: {fmtUsd(sub.cost_usd)}
            </span>
          ))}
        </div>
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
                    {isVerifiedClean && <span style={{ color: '#22c55e' }}>✓ clean</span>}
                    {checkCost ? <span style={{ color: 'var(--color-text-muted)' }}>· {fmtUsd(checkCost)}</span> : null}
                  </div>
                </div>
                {/* Open */}
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
    </div>
  )
}
