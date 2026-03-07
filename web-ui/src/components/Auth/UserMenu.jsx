import { useState, useRef, useEffect } from 'react'
import { useAuthStore } from '../../stores/useAuthStore'

/**
 * User avatar + dropdown menu shown in the header when authenticated.
 * Only rendered when auth is enabled.
 */
export default function UserMenu() {
  const { user, authRequired, logout } = useAuthStore()
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  if (!authRequired || !user) return null

  const initials = (user.name || user.email || '?')
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className="relative" ref={menuRef}>
      {/* Avatar button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500"
        title={user.name || user.email}
        aria-label="User menu"
      >
        {user.avatar_url ? (
          <img
            src={user.avatar_url}
            alt={user.name || 'User avatar'}
            className="w-8 h-8 rounded-full object-cover"
          />
        ) : (
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold text-white"
            style={{ backgroundColor: '#3b82f6' }}
          >
            {initials}
          </div>
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute right-0 mt-2 w-56 rounded-xl shadow-lg z-50 py-1"
          style={{
            backgroundColor: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* User info */}
          <div
            className="px-4 py-3 border-b"
            style={{ borderColor: 'var(--color-border)' }}
          >
            {user.name && (
              <p
                className="text-sm font-semibold truncate"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {user.name}
              </p>
            )}
            {user.email && (
              <p
                className="text-xs truncate"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {user.email}
              </p>
            )}
            <p
              className="text-xs mt-1 capitalize"
              style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}
            >
              via {user.provider}
            </p>
          </div>

          {/* Actions */}
          <button
            onClick={() => { setOpen(false); logout() }}
            className="w-full text-left px-4 py-2 text-sm transition-colors hover:bg-red-500 hover:text-white"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
