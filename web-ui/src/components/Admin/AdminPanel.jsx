import { useState, useEffect, useCallback } from 'react'
import {
  getAdminOverview,
  getAdminUsers,
  getAdminUserSessions,
  getAdminCheckDetail,
} from '../../utils/api'
import { getEffectiveReferenceStatus } from '../../utils/referenceStatus'

/**
 * Admin analytics dashboard.
 *
 * Drill-down: Overview -> Users -> Sessions -> Checks -> References. Sessions
 * are synthesised server-side from check timestamps (there is no sessions
 * table), so a "session" here means one sitting by one user.
 *
 * Deliberately shows real names and emails: the whole point is to look at an
 * individual's activity. The pre-existing /api/admin/activity endpoint stays
 * anonymised for the cases that only need aggregates.
 */

const WINDOWS = [
  { label: '7 days', value: 7 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
  { label: 'All time', value: 0 },
]

const num = (n) => (typeof n === 'number' ? n.toLocaleString() : '0')

// The API already returns percentages (see admin_insights._rate), so this must
// not scale again.
const pct = (rate) => (typeof rate === 'number' ? `${rate.toFixed(1)}%` : '—')
const formatDuration = (seconds) => {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m ${seconds % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

const formatMs = (ms) => (ms ? `${(ms / 1000).toFixed(1)}s` : '—')

const formatTime = (ts) => {
  if (!ts) return '—'
  // Timestamps are stored as naive UTC ("YYYY-MM-DD HH:MM:SS").
  const parsed = new Date(ts.includes('T') ? ts : `${ts.replace(' ', 'T')}Z`)
  return Number.isNaN(parsed.getTime()) ? ts : parsed.toLocaleString()
}

// Status colours mirror ReferenceCard.getStatusColor so a reference looks the
// same here as it does everywhere else. Hallucination has its own hue (orange)
// and must not be shown as a plain error.
const STATUS_ICONS = {
  hallucination: { icon: '🚫', label: 'Hallucinated', color: 'var(--color-hallucination)' },
  error: { icon: '❌', label: 'Error', color: 'var(--color-error)' },
  warning: { icon: '⚠️', label: 'Warning', color: 'var(--color-warning)' },
  suggestion: { icon: '💡', label: 'Suggestion', color: 'var(--color-suggestion)' },
  verified: { icon: '✅', label: 'Verified', color: 'var(--color-success)' },
  unverified: { icon: '❔', label: 'Unverified', color: 'var(--color-text-muted)' },
  checking: { icon: '⏳', label: 'Checking', color: 'var(--color-accent)' },
}

function Stat({ label, value, sub, tone }) {
  return (
    <div
      className="rounded-xl px-4 py-3"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        {label}
      </div>
      <div
        className="text-2xl font-semibold mt-1"
        style={{ color: tone || 'var(--color-text-primary)' }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
          {sub}
        </div>
      )}
    </div>
  )
}

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/**
 * Format a ``YYYY-MM-DD`` bucket key as ``Aug 10``. Parsed by hand rather than
 * via ``new Date()`` so the label never shifts a day due to the local timezone.
 */
function formatDayLabel(day) {
  if (typeof day !== 'string') return ''
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.trim())
  if (!match) return day
  const month = MONTH_NAMES[Number(match[2]) - 1]
  if (!month) return day
  return `${month} ${Number(match[3])}`
}

/**
 * Pick which bars get an x-axis label so they never overlap. Always labels the
 * first and last day, then spaces the rest evenly.
 */
function pickLabelIndices(count, maxLabels = 8) {
  if (count <= maxLabels) {
    return daysRange(count)
  }
  const step = Math.ceil((count - 1) / (maxLabels - 1))
  const indices = []
  for (let i = 0; i < count - 1; i += step) indices.push(i)
  indices.push(count - 1)
  // Drop the second-to-last label if crowding against the final one.
  if (indices.length > 1 && count - 1 - indices[indices.length - 2] < step / 2) {
    indices.splice(indices.length - 2, 1)
  }
  return indices
}

function daysRange(count) {
  const out = []
  for (let i = 0; i < count; i += 1) out.push(i)
  return out
}

/**
 * Inline SVG bar chart. The project has no chart library and this panel is not
 * worth adding one for.
 */
function DailyChart({ daily }) {
  if (!daily || daily.length === 0) {
    return (
      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
        No activity in this window.
      </p>
    )
  }

  const width = 640
  const plotHeight = 120
  const axisHeight = 22
  const height = plotHeight + axisHeight
  const max = Math.max(...daily.map((d) => d.checks), 1)
  const barWidth = width / daily.length
  const labelIndices = new Set(pickLabelIndices(daily.length))

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      aria-label="Checks per day"
      style={{ height: `${height}px` }}
    >
      {daily.map((d, i) => {
        const h = Math.max((d.checks / max) * (plotHeight - 16), d.checks > 0 ? 2 : 0)
        return (
          <rect
            key={d.day || i}
            x={i * barWidth + 1}
            y={plotHeight - h}
            width={Math.max(barWidth - 2, 1)}
            height={h}
            fill="var(--color-accent)"
          >
            <title>{`${d.day}: ${d.checks} checks, ${d.references_checked} refs, ${d.hallucinations} hallucinated`}</title>
          </rect>
        )
      })}

      <line
        x1={0}
        y1={plotHeight + 0.5}
        x2={width}
        y2={plotHeight + 0.5}
        stroke="var(--color-border)"
        strokeWidth={1}
      />

      {daily.map((d, i) => {
        if (!labelIndices.has(i)) return null
        const center = i * barWidth + barWidth / 2
        const isFirst = i === 0
        const isLast = i === daily.length - 1
        return (
          <text
            key={`label-${d.day || i}`}
            x={isFirst ? 0 : isLast ? width : center}
            y={plotHeight + 15}
            textAnchor={isFirst ? 'start' : isLast ? 'end' : 'middle'}
            fontSize={11}
            fill="var(--color-text-secondary)"
          >
            {formatDayLabel(d.day)}
          </text>
        )
      })}
    </svg>
  )
}

function Breakdown({ title, rows }) {
  if (!rows || rows.length === 0) return null
  const total = rows.reduce((sum, r) => sum + r.count, 0) || 1
  return (
    <div>
      <h4
        className="text-xs font-semibold uppercase tracking-wide mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {title}
      </h4>
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.name} className="flex items-center gap-2 text-sm">
            <span className="truncate flex-1" style={{ color: 'var(--color-text-primary)' }}>
              {r.name}
            </span>
            <span style={{ color: 'var(--color-text-secondary)' }}>{num(r.count)}</span>
            <span
              className="text-xs w-12 text-right"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {((r.count / total) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function OverviewTab({ overview }) {
  if (!overview) return null
  const t = overview.totals || {}
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat
          label="Users"
          value={num(t.active_users)}
          sub={`${num(t.total_users)} registered`}
        />
        <Stat label="Checks" value={num(t.checks)} sub={`${num(t.distinct_papers)} distinct papers`} />
        <Stat
          label="References"
          value={num(t.references_checked)}
          sub={t.avg_references_per_check ? `${t.avg_references_per_check} avg/check` : null}
        />
        <Stat
          label="Hallucinated"
          value={num(t.hallucinations)}
          sub={`${pct(t.hallucination_rate)} of refs`}
          tone="var(--color-hallucination)"
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Verified" value={num(t.references_verified)} sub={pct(t.verified_rate)} tone="var(--color-success)" />
        <Stat label="Errors" value={num(t.errors)} tone="var(--color-error)" />
        <Stat label="Warnings" value={num(t.warnings)} tone="var(--color-warning)" />
        <Stat label="Avg duration" value={formatMs(t.avg_duration_ms)} />
      </div>

      <div>
        <h4
          className="text-xs font-semibold uppercase tracking-wide mb-2"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Checks per day
        </h4>
        <DailyChart daily={overview.daily} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <Breakdown title="Source types" rows={overview.breakdowns?.source_types} />
        <Breakdown title="Extraction methods" rows={overview.breakdowns?.extraction_methods} />
        <Breakdown title="Models" rows={overview.breakdowns?.models} />
        <Breakdown title="Failure classes" rows={overview.breakdowns?.failure_classes} />
      </div>
    </div>
  )
}

function UsersTab({ data, onSelectUser }) {
  if (!data) return null
  const users = data.users || []
  return (
    <div className="space-y-3">
      {data.unattributed?.checks > 0 && (
        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          {num(data.unattributed.checks)} checks are not attributed to a user (recorded before
          sign-in was required, or run in single-user mode).
        </p>
      )}
      {users.length === 0 && (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          No users yet.
        </p>
      )}
      {users.map((u) => (
        <button
          key={u.id}
          type="button"
          onClick={() => onSelectUser(u)}
          className="w-full text-left rounded-xl px-4 py-3 transition-colors"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div
                className="text-sm font-semibold truncate"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {u.name || u.email || `User ${u.id}`}
                {u.is_admin && (
                  <span
                    className="ml-2 text-xs font-normal px-1.5 py-0.5 rounded"
                    style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
                  >
                    admin
                  </span>
                )}
              </div>
              <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>
                {u.email} · via {u.provider} · last active {formatTime(u.last_check_at)}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                {num(u.checks)} checks
              </div>
              <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {num(u.references_checked)} refs ·{' '}
                <span style={{ color: 'var(--color-hallucination)' }}>
                  {num(u.hallucinations)} hallucinated
                </span>
              </div>
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}

function SessionsTab({ sessions, loading, onSelectCheck, onBack, user }) {
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onBack}
        className="text-xs px-2 py-1 -ml-2 rounded-lg transition-colors"
        style={{ color: 'var(--color-accent)' }}
      >
        ← Back to users
      </button>
      <div>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
          {user?.name || user?.email || `User ${user?.id}`}
        </h3>
        <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          {user?.email}
        </p>
      </div>

      {loading && (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Loading sessions…
        </p>
      )}

      {!loading && sessions?.length === 0 && (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          This user has not run any checks in this window.
        </p>
      )}

      {sessions?.map((s, i) => (
        <div
          key={`${s.started_at}-${i}`}
          className="rounded-xl p-3"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div className="flex items-center justify-between gap-3 mb-2">
            <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {formatTime(s.started_at)}
            </div>
            <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              {formatDuration(s.duration_seconds)} · {num(s.checks)} papers ·{' '}
              {num(s.references_checked)} refs ·{' '}
              <span style={{ color: 'var(--color-hallucination)' }}>
                {num(s.hallucinations)} hallucinated
              </span>
            </div>
          </div>
          <div className="space-y-1">
            {s.items?.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onSelectCheck(c.id)}
                className="w-full text-left px-2 py-1.5 rounded-lg text-xs flex items-center justify-between gap-2 transition-colors"
                style={{ color: 'var(--color-text-primary)' }}
              >
                <span className="truncate">
                  {c.paper_title || c.paper_source || `Check ${c.id}`}
                </span>
                <span className="shrink-0" style={{ color: 'var(--color-text-secondary)' }}>
                  {num(c.total_refs)} refs
                  {c.hallucination_count > 0 && (
                    <span style={{ color: 'var(--color-hallucination)' }}>
                      {' '}
                      · {num(c.hallucination_count)} hallucinated
                    </span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function CheckTab({ check, loading, onBack }) {
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onBack}
        className="text-xs px-2 py-1 -ml-2 rounded-lg transition-colors"
        style={{ color: 'var(--color-accent)' }}
      >
        ← Back to sessions
      </button>

      {loading && (
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Loading check…
        </p>
      )}

      {!loading && check && (
        <>
          <div>
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {check.paper_title || check.paper_source}
            </h3>
            <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              {formatTime(check.timestamp)} · {check.status} ·{' '}
              {check.llm_model || 'no model recorded'} ·{' '}
              {check.extraction_method || 'unknown extraction'}
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="References" value={num(check.total_refs)} />
            <Stat label="Verified" value={num(check.refs_verified)} tone="var(--color-success)" />
            <Stat label="Errors" value={num(check.errors_count)} tone="var(--color-error)" />
            <Stat
              label="Hallucinated"
              value={num(check.hallucination_count)}
              tone="var(--color-hallucination)"
            />
          </div>

          <div className="space-y-1">
            {(check.references || []).map((ref, i) => {
              const status = getEffectiveReferenceStatus(ref, true)
              const meta = STATUS_ICONS[status] || STATUS_ICONS.unverified
              return (
                <div
                  key={i}
                  className="flex items-start gap-2 px-2 py-1.5 rounded-lg text-xs"
                  style={{
                    backgroundColor: 'var(--color-bg-primary)',
                    border: '1px solid var(--color-border)',
                    borderLeft: `3px solid ${meta.color}`,
                  }}
                >
                  <span title={meta.label} aria-label={meta.label}>
                    {meta.icon}
                  </span>
                  <span className="flex-1 min-w-0" style={{ color: 'var(--color-text-primary)' }}>
                    <span className="block truncate">{ref.title || '(untitled reference)'}</span>
                    {ref.authors && (
                      <span
                        className="block truncate"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        {Array.isArray(ref.authors) ? ref.authors.join(', ') : ref.authors}
                        {ref.year ? ` (${ref.year})` : ''}
                      </span>
                    )}
                  </span>
                </div>
              )
            })}
            {(check.references || []).length === 0 && (
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                No per-reference detail was stored for this check.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function AdminPanel({ open, onClose }) {
  const [tab, setTab] = useState('overview')
  const [days, setDays] = useState(30)
  const [overview, setOverview] = useState(null)
  const [users, setUsers] = useState(null)
  const [selectedUser, setSelectedUser] = useState(null)
  const [sessions, setSessions] = useState(null)
  const [check, setCheck] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [ov, us] = await Promise.all([getAdminOverview(days), getAdminUsers(days)])
      setOverview(ov.data)
      setUsers(us.data)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load admin data')
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  const selectUser = async (user) => {
    setSelectedUser(user)
    setTab('sessions')
    setLoading(true)
    setError(null)
    try {
      const res = await getAdminUserSessions(user.id, days)
      setSessions(res.data.sessions || [])
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  const selectCheck = async (checkId) => {
    setTab('check')
    setLoading(true)
    setError(null)
    try {
      const res = await getAdminCheckDetail(checkId)
      setCheck(res.data)
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to load check')
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  const usersTabActive = tab === 'users' || tab === 'sessions' || tab === 'check'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl shadow-2xl overflow-hidden flex flex-col"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          width: '860px',
          maxWidth: '95vw',
          height: '680px',
          maxHeight: '95vh',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-5 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Admin dashboard
          </h2>
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="text-xs rounded-lg px-2 py-1"
              aria-label="Time window"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
            >
              {WINDOWS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close admin dashboard"
              className="text-sm px-2 py-1 rounded-lg transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              ✕
            </button>
          </div>
        </div>

        <div className="flex gap-1 px-5 pt-3">
          {['overview', 'users'].map((t) => {
            const active = t === 'overview' ? tab === 'overview' : usersTabActive
            return (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                aria-pressed={active}
                className={`text-xs px-3 py-1.5 rounded-lg capitalize transition-colors ${
                  active ? 'font-semibold' : ''
                }`}
                style={{
                  backgroundColor: active ? 'var(--color-bg-tertiary)' : 'transparent',
                  color: active ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                }}
              >
                {t}
              </button>
            )
          })}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <p className="text-sm mb-3" style={{ color: 'var(--color-error)' }}>
              {error}
            </p>
          )}
          {loading && tab === 'overview' && (
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Loading…
            </p>
          )}
          {tab === 'overview' && !loading && <OverviewTab overview={overview} />}
          {tab === 'users' && <UsersTab data={users} onSelectUser={selectUser} />}
          {tab === 'sessions' && (
            <SessionsTab
              sessions={sessions}
              loading={loading}
              user={selectedUser}
              onSelectCheck={selectCheck}
              onBack={() => setTab('users')}
            />
          )}
          {tab === 'check' && (
            <CheckTab check={check} loading={loading} onBack={() => setTab('sessions')} />
          )}
        </div>
      </div>
    </div>
  )
}
