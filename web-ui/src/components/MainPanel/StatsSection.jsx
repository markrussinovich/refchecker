import { useCheckStore } from '../../stores/useCheckStore'

/**
 * Stats section showing reference check summary with clickable filters
 */
export default function StatsSection({ stats, isComplete }) {
  const { statusFilter, setStatusFilter, clearStatusFilter } = useCheckStore()

  const cards = [
    {
      id: 'verified',
      label: 'Verified',
      value: stats.verified_count || 0,
      color: 'var(--color-success)',
      bgColor: 'var(--color-success-bg)',
      icon: (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
          <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ),
    },
    {
      id: 'error',
      label: 'Errors',
      value: stats.errors_count || 0,
      color: 'var(--color-error)',
      bgColor: 'var(--color-error-bg)',
      icon: (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
          <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
          <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
        </svg>
      ),
    },
    {
      id: 'warning',
      label: 'Warnings',
      value: stats.warnings_count || 0,
      color: 'var(--color-warning)',
      bgColor: 'var(--color-warning-bg)',
      icon: (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="var(--color-warning)" />
          <path d="M12 7.5v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
          <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
        </svg>
      ),
    },
    {
      id: 'unverified',
      label: 'Unverified',
      value: stats.unverified_count || 0,
      color: 'var(--color-text-muted)',
      bgColor: 'var(--color-bg-tertiary)',
      icon: (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
          <path d="M10.75 9.5c.1-1.1.95-2 2.2-2 1.21 0 2.2.89 2.2 1.99 0 .86-.56 1.6-1.4 1.83-.55.15-.95.63-.95 1.2v.23" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="12" cy="16" r="1" fill="#fff" />
        </svg>
      ),
    },
  ]

  const handleCardClick = (cardId) => {
    setStatusFilter(cardId)
  }

  const isFilterActive = statusFilter.length > 0

  return (
    <div 
      className="rounded-lg border p-4"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 
            className="font-semibold"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Summary
          </h3>
          <span 
            className="text-sm"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {stats.total_refs || 0} references
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!isComplete && stats.processed_refs > 0 && (
            <span 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {stats.processed_refs} / {stats.total_refs} processed
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {cards.map(card => {
          const isSelected = statusFilter.includes(card.id)
          
          return (
            <button
              key={card.label}
              onClick={() => handleCardClick(card.id)}
              className="rounded-xl p-3 text-center transition-all cursor-pointer border-2 hover:scale-[1.02] active:scale-[0.98]"
              style={{ 
                backgroundColor: isSelected ? card.bgColor : 'var(--color-bg-primary)',
                borderColor: isSelected ? card.color : 'var(--color-border)',
                boxShadow: isSelected ? `0 0 0 1px ${card.color}` : 'none',
              }}
              title={`Click to filter by ${card.label.toLowerCase()}`}
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
            </button>
          )
        })}
      </div>
    </div>
  )
}
