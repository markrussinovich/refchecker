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
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
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
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ),
          color: 'var(--color-success)',
          bgColor: 'var(--color-success-bg)',
          label: 'Verified',
        }
      case 'error':
        return {
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          ),
          color: 'var(--color-error)',
          bgColor: 'var(--color-error-bg)',
          label: 'Error',
        }
      case 'warning':
        return {
          icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
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
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
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
      className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center"
      style={{ 
        backgroundColor: indicator.bgColor,
        color: indicator.color
      }}
      title={indicator.label}
    >
      {indicator.icon}
    </div>
  )
}
