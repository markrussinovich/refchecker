/**
 * Status indicator icon for references
 */
export default function StatusIndicator({ status }) {
  const getIndicator = () => {
    switch (status?.toLowerCase()) {
      case 'checking':
      case 'pending':
        return {
          icon: (
            <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ),
          color: 'var(--color-accent)',
          bgColor: 'var(--color-info-bg)',
          label: 'Checking...',
        }
      case 'verified':
        return {
          icon: (
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
              <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ),
          color: 'var(--color-success)',
          bgColor: 'var(--color-success-bg)',
          label: 'Verified',
        }
      case 'error':
        return {
          icon: (
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
              <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
              <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
            </svg>
          ),
          color: 'var(--color-error)',
          bgColor: 'var(--color-error-bg)',
          label: 'Error',
        }
      case 'warning':
        return {
          icon: (
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-warning)" />
              <path d="M12 7.5v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
              <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
            </svg>
          ),
          color: 'var(--color-warning)',
          bgColor: 'var(--color-warning-bg)',
          label: 'Warning',
        }
      case 'unverified':
      default:
        return {
          icon: (
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
              <path d="M10.75 9.5c.1-1.1.95-2 2.2-2 1.21 0 2.2.89 2.2 1.99 0 .86-.56 1.6-1.4 1.83-.55.15-.95.63-.95 1.2v.23" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="12" cy="16" r="1" fill="#fff" />
            </svg>
          ),
          color: 'var(--color-text-muted)',
          bgColor: 'var(--color-bg-tertiary)',
          label: 'Unverified',
        }
    }
  }

  const indicator = getIndicator()

  return (
    <div
      className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
      style={{ 
        backgroundColor: 'transparent',
        color: indicator.color
      }}
      title={indicator.label}
    >
      {indicator.icon}
    </div>
  )
}
