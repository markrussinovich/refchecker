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
                className="mt-1 text-xs space-y-1 ml-4"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {item.cited_value && (
                  <div className="flex">
                    <span className="font-medium flex-shrink-0" style={{ width: '60px' }}>cited:</span>
                    <span>{item.cited_value}</span>
                  </div>
                )}
                {item.actual_value && (
                  <div className="flex">
                    <span className="font-medium flex-shrink-0" style={{ width: '60px' }}>actual:</span>
                    <span>{item.actual_value}</span>
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
