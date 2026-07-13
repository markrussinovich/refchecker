import { usePresence } from '../../hooks/usePresence'
import { useAuthStore } from '../../stores/useAuthStore'

/**
 * Presence-avatars strip (issue #67) — shows the team members currently
 * viewing the same shared batch/check. Driven entirely by real WebSocket
 * presence (usePresence): no avatar appears unless that user's socket is
 * connected right now.
 *
 * Renders nothing when only the current user is present (or in single-user
 * mode), so it stays quiet until collaboration actually happens.
 *
 * @param {string|number} roomId  the batch id (or check id) to subscribe to
 */
const PALETTE = ['#3b82f6', '#8b5cf6', '#ec4899', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']

function initialsOf(u) {
  return (u.name || u.email || '?')
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

function colorFor(userId) {
  return PALETTE[Math.abs(Number(userId) || 0) % PALETTE.length]
}

export default function PresenceAvatars({ roomId }) {
  const { user } = useAuthStore()
  const users = usePresence(roomId)

  // Only worth showing once someone *other* than the current user is here.
  const others = users.filter((u) => u.user_id !== user?.id)
  if (others.length === 0) return null

  const shown = others.slice(0, 5)
  const overflow = others.length - shown.length
  const label = `${others.length} other ${others.length === 1 ? 'person' : 'people'} viewing this batch`

  return (
    <div className="flex items-center gap-1.5" title={label} aria-label={label}>
      <div className="flex -space-x-2">
        {shown.map((u) => (
          <div
            key={u.user_id}
            className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold text-white ring-2"
            style={{ backgroundColor: colorFor(u.user_id), '--tw-ring-color': 'var(--color-bg-secondary)' }}
            title={u.name || u.email || `User ${u.user_id}`}
          >
            {initialsOf(u)}
          </div>
        ))}
        {overflow > 0 && (
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold ring-2"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              color: 'var(--color-text-secondary)',
              '--tw-ring-color': 'var(--color-bg-secondary)',
            }}
            title={`+${overflow} more`}
          >
            +{overflow}
          </div>
        )}
      </div>
      <span className="hidden sm:inline text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        viewing now
      </span>
    </div>
  )
}
