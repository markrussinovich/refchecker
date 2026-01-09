/**
 * Error/warning details display
 */
export default function ErrorDetails({ title, items, type }) {
  const colorConfig = type === 'error' 
    ? { text: 'var(--color-error)', bg: 'var(--color-error-bg)' }
    : { text: 'var(--color-warning)', bg: 'var(--color-warning-bg)' }

  return (
    <div>
      <h4 
        className="text-xs font-medium mb-1"
        style={{ color: colorConfig.text }}
      >
        {title} ({items.length})
      </h4>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div
            key={i}
            className="p-2 rounded text-sm"
            style={{ backgroundColor: colorConfig.bg }}
          >
            <div 
              className="font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {item.error_type}: {item.error_details}
            </div>
            {(item.cited_value || item.actual_value) && (
              <div 
                className="mt-1 text-xs space-y-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {item.cited_value && (
                  <div>
                    <span className="font-medium">Cited:</span> {item.cited_value}
                  </div>
                )}
                {item.actual_value && (
                  <div>
                    <span className="font-medium">Actual:</span> {item.actual_value}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
