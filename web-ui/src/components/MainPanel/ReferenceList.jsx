import ReferenceCard from '../ReferenceCard/ReferenceCard'

/**
 * List of references being checked
 */
export default function ReferenceList({ references, isLoading }) {
  if (isLoading) {
    return (
      <div 
        className="rounded-lg border p-8 text-center"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <svg 
          className="animate-spin h-8 w-8 mx-auto mb-3" 
          fill="none" 
          viewBox="0 0 24 24"
          style={{ color: 'var(--color-accent)' }}
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p style={{ color: 'var(--color-text-muted)' }}>
          Loading references...
        </p>
      </div>
    )
  }

  if (!references || references.length === 0) {
    return (
      <div 
        className="rounded-lg border p-8 text-center"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          borderColor: 'var(--color-border)',
        }}
      >
        <svg 
          className="w-12 h-12 mx-auto mb-3 opacity-50" 
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p style={{ color: 'var(--color-text-muted)' }}>
          No references extracted yet
        </p>
        <p 
          className="text-sm mt-1"
          style={{ color: 'var(--color-text-muted)' }}
        >
          References will appear here as they are found
        </p>
      </div>
    )
  }

  return (
    <div 
      className="rounded-lg border overflow-hidden"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      <div 
        className="px-4 py-3 border-b"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <h3 
          className="font-semibold"
          style={{ color: 'var(--color-text-primary)' }}
        >
          References ({references.length})
        </h3>
      </div>

      <div className="divide-y" style={{ borderColor: 'var(--color-border)' }}>
        {references.map((ref, index) => (
          <ReferenceCard 
            key={ref.index ?? index} 
            reference={ref} 
            index={ref.index ?? index}
            totalRefs={references.length}
          />
        ))}
      </div>
    </div>
  )
}
