import { useState, useRef, useEffect, useCallback } from 'react'
import { useAuthStore } from '../../stores/useAuthStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { getTeams, createTeam, getTeamMembers, addTeamMember, removeTeamMember, leaveTeam, getTeamActivity, getTeamChecks } from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Team switcher / menu in the header (issue #66). Lists the teams the current
 * user owns or belongs to, shows the selected team's members, and lets the
 * owner create a team or add a member by email.
 *
 * Only rendered when auth is enabled (teams require real OAuth users); mirrors
 * UserMenu's outside-click-close pattern and uses theme CSS vars.
 */
export default function TeamMenu() {
  const { user, authRequired } = useAuthStore()
  const selectCheck = useHistoryStore((s) => s.selectCheck)
  const [open, setOpen] = useState(false)
  const [teams, setTeams] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [members, setMembers] = useState([])
  const [activity, setActivity] = useState([])
  const [teamChecks, setTeamChecks] = useState([])
  const [newTeamName, setNewTeamName] = useState('')
  const [memberEmail, setMemberEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const menuRef = useRef(null)

  useEffect(() => {
    const onDown = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const loadTeams = useCallback(async () => {
    try {
      const resp = await getTeams()
      const list = resp.data.teams || []
      setTeams(list)
      setSelectedId((prev) => (prev && list.some((t) => t.id === prev) ? prev : (list[0]?.id ?? null)))
    } catch (e) {
      logger.error('TeamMenu', 'Failed to load teams', e)
      setError('Could not load teams')
    }
  }, [])

  const loadMembers = useCallback(async (teamId) => {
    if (!teamId) { setMembers([]); return }
    try {
      const resp = await getTeamMembers(teamId)
      setMembers(resp.data.members || [])
    } catch (e) {
      logger.error('TeamMenu', 'Failed to load members', e)
      setMembers([])
    }
  }, [])

  const loadActivity = useCallback(async (teamId) => {
    if (!teamId) { setActivity([]); return }
    try {
      const resp = await getTeamActivity(teamId)
      setActivity(resp.data.activity || [])
    } catch (e) {
      logger.error('TeamMenu', 'Failed to load activity', e)
      setActivity([])
    }
  }, [])

  const loadTeamChecks = useCallback(async (teamId) => {
    if (!teamId) { setTeamChecks([]); return }
    try {
      const resp = await getTeamChecks(teamId)
      setTeamChecks(resp.data.checks || [])
    } catch (e) {
      logger.error('TeamMenu', 'Failed to load team checks', e)
      setTeamChecks([])
    }
  }, [])

  // Load teams when the menu opens.
  useEffect(() => { if (open) loadTeams() }, [open, loadTeams])
  // Load members + activity + shared checks whenever the selected team changes (while open).
  useEffect(() => {
    if (open) { loadMembers(selectedId); loadActivity(selectedId); loadTeamChecks(selectedId) }
  }, [open, selectedId, loadMembers, loadActivity, loadTeamChecks])

  if (!authRequired || !user) return null

  const selectedTeam = teams.find((t) => t.id === selectedId) || null
  const isOwner = selectedTeam && selectedTeam.owner_user_id === user.id

  const handleCreate = async () => {
    const name = newTeamName.trim()
    if (!name) return
    setBusy(true); setError('')
    try {
      const resp = await createTeam(name)
      setNewTeamName('')
      await loadTeams()
      const created = resp.data.team
      if (created?.id) setSelectedId(created.id)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not create team')
    } finally {
      setBusy(false)
    }
  }

  const handleAddMember = async () => {
    const email = memberEmail.trim()
    if (!email || !selectedId) return
    setBusy(true); setError('')
    try {
      const resp = await addTeamMember(selectedId, { email })
      setMemberEmail('')
      setMembers(resp.data.members || [])
      await loadTeams() // refresh member counts
      await loadActivity(selectedId)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not add member')
    } finally {
      setBusy(false)
    }
  }

  const handleRemoveMember = async (userId) => {
    if (!selectedId || !userId) return
    setBusy(true); setError('')
    try {
      const resp = await removeTeamMember(selectedId, userId)
      setMembers(resp.data.members || [])
      await loadTeams() // refresh member counts
      await loadActivity(selectedId)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not remove member')
    } finally {
      setBusy(false)
    }
  }

  const handleLeave = async () => {
    if (!selectedId) return
    setBusy(true); setError('')
    try {
      await leaveTeam(selectedId)
      setSelectedId(null)
      await loadTeams()
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not leave team')
    } finally {
      setBusy(false)
    }
  }

  // Render one audit-log entry as a human sentence: who did what to whom.
  const shortName = (email) => (email ? String(email).split('@')[0] : '')
  const activityText = (a) => {
    const actor = shortName(a.actor_email) || 'Someone'
    const target = shortName(a.target_email)
    switch (a.action) {
      case 'created_team': return `${actor} created the team`
      case 'added_member': return `${actor} added ${target || 'a member'}${a.detail && a.detail !== 'member' ? ` as ${a.detail}` : ''}`
      case 'removed_member': return `${actor} removed ${target || 'a member'}`
      case 'left_team': return `${actor} left the team`
      default: return `${actor} · ${a.action}`
    }
  }
  const fmtWhen = (s) => {
    if (!s) return ''
    // SQLite CURRENT_TIMESTAMP is UTC without a zone — append Z so it parses as UTC.
    const d = new Date(String(s).replace(' ', 'T') + 'Z')
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-gray-400 hover:text-gray-200 transition-colors flex items-center"
        aria-label="Teams"
        title="Teams"
      >
        <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a3 3 0 10-2.5-1.34M5 12.66A3 3 0 117 7" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 mt-2 w-72 rounded-xl shadow-lg z-50 py-1"
          style={{ backgroundColor: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
          <div className="px-3 py-1.5 text-xs font-semibold" style={{ color: 'var(--color-text-muted)' }}>
            Teams
          </div>

          {/* Team switcher */}
          {teams.length > 0 ? (
            <div className="px-3 pb-2">
              <select
                value={selectedId ?? ''}
                onChange={(e) => setSelectedId(Number(e.target.value))}
                className="w-full text-sm rounded-md px-2 py-1.5"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.member_count})
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className="px-3 pb-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              You are not in any team yet.
            </p>
          )}

          {/* Members of the selected team */}
          {selectedTeam && (
            <div className="px-3 pb-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
              <p className="text-xs font-semibold mt-2 mb-1" style={{ color: 'var(--color-text-muted)' }}>
                Members
              </p>
              <ul className="max-h-40 overflow-y-auto space-y-1">
                {members.map((m) => (
                  <li key={m.user_id} className="flex items-center justify-between text-sm gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <span className="truncate flex-1 min-w-0">{m.name || m.email || `User ${m.user_id}`}</span>
                    <span className="text-xs flex-none" style={{ color: 'var(--color-text-secondary)' }}>{m.role}</span>
                    {/* Owner can remove anyone except the owner. */}
                    {isOwner && m.user_id !== selectedTeam.owner_user_id && (
                      <button
                        type="button"
                        onClick={() => handleRemoveMember(m.user_id)}
                        disabled={busy}
                        className="text-xs flex-none disabled:opacity-50 hover:opacity-80"
                        style={{ color: 'var(--color-error, #ef4444)' }}
                        aria-label={`Remove ${m.name || m.email || `user ${m.user_id}`}`}
                        title="Remove member"
                      >
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>

              {/* Leave the team (hidden for an owner who still has other members). */}
              {!(isOwner && members.length > 1) && (
                <button
                  type="button"
                  onClick={handleLeave}
                  disabled={busy}
                  className="text-xs mt-2 disabled:opacity-50 hover:opacity-80"
                  style={{ color: 'var(--color-error, #ef4444)' }}
                  title="Leave this team"
                >
                  Leave team
                </button>
              )}

              {/* Owner-only: add a member by email */}
              {isOwner && (
                <div className="flex gap-1 mt-2">
                  <input
                    type="email"
                    value={memberEmail}
                    onChange={(e) => setMemberEmail(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleAddMember() }}
                    placeholder="member@email.com"
                    className="flex-1 text-sm rounded-md px-2 py-1.5 min-w-0"
                    style={{
                      backgroundColor: 'var(--color-bg-primary)',
                      color: 'var(--color-text-primary)',
                      border: '1px solid var(--color-border)',
                    }}
                  />
                  <button
                    type="button"
                    onClick={handleAddMember}
                    disabled={busy || !memberEmail.trim()}
                    className="text-sm rounded-md px-2.5 py-1.5 flex-none disabled:opacity-50"
                    style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: '#fff' }}
                  >
                    Add
                  </button>
                </div>
              )}

              {/* Activity log — who created the team, added/removed which member, who left. */}
              <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>Activity</p>
                {activity.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>No activity yet.</p>
                ) : (
                  <ul className="max-h-40 overflow-y-auto space-y-1">
                    {activity.map((a) => (
                      <li key={a.id} className="text-xs flex items-baseline justify-between gap-2">
                        <span className="truncate min-w-0" style={{ color: 'var(--color-text-secondary)' }}>{activityText(a)}</span>
                        <span className="flex-none whitespace-nowrap" style={{ color: 'var(--color-text-muted)' }}>{fmtWhen(a.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Shared checks — checks any member shared with this team (R26). */}
              <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>Shared checks</p>
                {teamChecks.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>No checks shared with this team yet.</p>
                ) : (
                  <ul className="max-h-40 overflow-y-auto space-y-1">
                    {teamChecks.map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => { setOpen(false); selectCheck?.(c.id) }}
                          className="w-full text-left text-xs truncate hover:opacity-80"
                          style={{ color: 'var(--color-text-primary)' }}
                          title={c.paper_title || c.paper_source || `Check #${c.id}`}
                        >
                          {c.paper_title || c.paper_source || `Check #${c.id}`}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {/* Create a new team */}
          <div className="px-3 py-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
            <p className="text-xs font-semibold mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Create a team
            </p>
            <div className="flex gap-1">
              <input
                type="text"
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
                placeholder="Team name"
                className="flex-1 text-sm rounded-md px-2 py-1.5 min-w-0"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  color: 'var(--color-text-primary)',
                  border: '1px solid var(--color-border)',
                }}
              />
              <button
                type="button"
                onClick={handleCreate}
                disabled={busy || !newTeamName.trim()}
                className="text-sm rounded-md px-2.5 py-1.5 flex-none disabled:opacity-50"
                style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: '#fff' }}
              >
                Create
              </button>
            </div>
          </div>

          {error && (
            <p className="px-3 pb-2 text-xs" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
          )}
        </div>
      )}
    </div>
  )
}
