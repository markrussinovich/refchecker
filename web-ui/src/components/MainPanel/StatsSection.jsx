/**
 * Stats section showing reference check summary
 */
export default function StatsSection({ stats, isComplete }) {
  const cards = [
    {
      label: 'Total',
      value: stats.total_refs || 0,
      color: 'var(--color-text-primary)',
      bgColor: 'var(--color-bg-tertiary)',
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
    },
    {
      label: 'Verified',
      value: stats.verified_count || 0,
      color: 'var(--color-success)',
      bgColor: 'var(--color-success-bg)',
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ),
    },
    {
      label: 'Errors',
      value: stats.errors_count || 0,
      color: 'var(--color-error)',
      bgColor: 'var(--color-error-bg)',
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ),
    },
    {
      label: 'Warnings',
      value: stats.warnings_count || 0,
      color: 'var(--color-warning)',
      bgColor: 'var(--color-warning-bg)',
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      ),
    },
    {
      label: 'Unverified',
      value: stats.unverified_count || 0,
      color: 'var(--color-text-muted)',
      bgColor: 'var(--color-bg-tertiary)',
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
  ]

  return (
    <div 
      className="rounded-lg border p-4"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <h3 
          className="font-semibold"
          style={{ color: 'var(--color-text-primary)' }}
        >
          Summary
        </h3>
        {!isComplete && stats.processed_refs > 0 && (
          <span 
            className="text-sm"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {stats.processed_refs} / {stats.total_refs} processed
          </span>
        )}
      </div>

      <div className="grid grid-cols-5 gap-3">
        {cards.map(card => (
          <div
            key={card.label}
            className="rounded-lg p-3 text-center transition-all"
            style={{ backgroundColor: card.bgColor }}
          >
            <div 
              className="flex justify-center mb-2"
              style={{ color: card.color }}
            >
              {card.icon}
            </div>
            <div 
              className="text-2xl font-bold"
              style={{ color: card.color }}
            >
              {card.value}
            </div>
            <div 
              className="text-xs mt-1"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {card.label}
            </div>
          </div>
        ))}
      </div>

      {/* Overall progress */}
      {!isComplete && stats.total_refs > 0 && (
        <div className="mt-4">
          <div 
            className="h-1.5 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--color-bg-tertiary)' }}
          >
            <div 
              className="h-full rounded-full transition-all duration-300 progress-bar"
              style={{ 
                width: `${stats.progress_percent || 0}%`,
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
