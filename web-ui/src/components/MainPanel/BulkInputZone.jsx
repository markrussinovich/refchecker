import { useCallback, useRef } from 'react'

/**
 * Bulk input component for multiple URLs or file uploads
 */
export default function BulkInputZone({
  bulkMode,
  setBulkMode,
  bulkUrls,
  setBulkUrls,
  bulkFiles,
  setBulkFiles,
  disabled,
}) {
  const fileInputRef = useRef(null)

  const handleFileChange = useCallback((e) => {
    const files = Array.from(e.target.files || [])
    // Filter to only supported file types
    const validFiles = files.filter(f => {
      const ext = f.name.toLowerCase()
      return ext.endsWith('.pdf') || ext.endsWith('.txt') || 
             ext.endsWith('.tex') || ext.endsWith('.bib') || 
             ext.endsWith('.bbl') || ext.endsWith('.zip')
    })
    setBulkFiles(prev => [...prev, ...validFiles].slice(0, 50)) // Max 50 files
  }, [setBulkFiles])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    if (disabled) return
    
    const files = Array.from(e.dataTransfer?.files || [])
    const validFiles = files.filter(f => {
      const ext = f.name.toLowerCase()
      return ext.endsWith('.pdf') || ext.endsWith('.txt') || 
             ext.endsWith('.tex') || ext.endsWith('.bib') || 
             ext.endsWith('.bbl') || ext.endsWith('.zip')
    })
    setBulkFiles(prev => [...prev, ...validFiles].slice(0, 50))
  }, [disabled, setBulkFiles])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const removeFile = useCallback((index) => {
    setBulkFiles(prev => prev.filter((_, i) => i !== index))
  }, [setBulkFiles])

  const clearAllFiles = useCallback(() => {
    setBulkFiles([])
  }, [setBulkFiles])

  const urlCount = bulkUrls.split('\n').filter(u => u.trim()).length

  return (
    <div className="space-y-4">
      {/* Sub-mode toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setBulkMode('urls')}
          disabled={disabled}
          className="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
          style={{
            backgroundColor: bulkMode === 'urls' 
              ? 'var(--color-accent-muted)' 
              : 'var(--color-bg-tertiary)',
            color: bulkMode === 'urls' 
              ? 'var(--color-accent)' 
              : 'var(--color-text-secondary)',
            border: bulkMode === 'urls' 
              ? '1px solid var(--color-accent)' 
              : '1px solid transparent',
          }}
          onMouseEnter={(e) => {
            if (!disabled && bulkMode !== 'urls') {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }
          }}
          onMouseLeave={(e) => {
            if (bulkMode !== 'urls') {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }
          }}
        >
          List of URLs
        </button>
        <button
          onClick={() => setBulkMode('files')}
          disabled={disabled}
          className="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
          style={{
            backgroundColor: bulkMode === 'files' 
              ? 'var(--color-accent-muted)' 
              : 'var(--color-bg-tertiary)',
            color: bulkMode === 'files' 
              ? 'var(--color-accent)' 
              : 'var(--color-text-secondary)',
            border: bulkMode === 'files' 
              ? '1px solid var(--color-accent)' 
              : '1px solid transparent',
          }}
          onMouseEnter={(e) => {
            if (!disabled && bulkMode !== 'files') {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
              e.currentTarget.style.color = 'var(--color-text-primary)'
            }
          }}
          onMouseLeave={(e) => {
            if (bulkMode !== 'files') {
              e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
              e.currentTarget.style.color = 'var(--color-text-secondary)'
            }
          }}
        >
          Multiple Files / ZIP
        </button>
      </div>

      {/* URLs input */}
      {bulkMode === 'urls' && (
        <div>
          <textarea
            value={bulkUrls}
            onChange={(e) => setBulkUrls(e.target.value)}
            placeholder={`Enter one URL or ArXiv ID per line:\n\n2401.12345\nhttps://arxiv.org/abs/2312.00001\n2309.12345v2\n...`}
            disabled={disabled}
            rows={8}
            className="w-full px-4 py-3 rounded-lg border focus:outline-none focus:ring-2 resize-y font-mono text-sm"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          />
          {urlCount > 0 && (
            <p 
              className="mt-2 text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {urlCount} paper{urlCount !== 1 ? 's' : ''} to check
              {urlCount > 50 && (
                <span style={{ color: 'var(--color-warning)' }}> (max 50, will be truncated)</span>
              )}
            </p>
          )}
        </div>
      )}

      {/* Files input */}
      {bulkMode === 'files' && (
        <div>
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => !disabled && fileInputRef.current?.click()}
            className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors"
            style={{
              borderColor: 'var(--color-border)',
              backgroundColor: 'var(--color-bg-primary)',
              opacity: disabled ? 0.5 : 1,
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.tex,.bib,.bbl,.zip"
              onChange={handleFileChange}
              className="hidden"
              disabled={disabled}
            />
            <div className="text-4xl mb-2">📁</div>
            <p style={{ color: 'var(--color-text-primary)' }}>
              Drop files here or click to select
            </p>
            <p 
              className="text-sm mt-1"
              style={{ color: 'var(--color-text-muted)' }}
            >
              PDF, TXT, TEX, BIB, BBL, or a ZIP archive (max 50 files)
            </p>
          </div>

          {/* File list */}
          {bulkFiles.length > 0 && (
            <div className="mt-3">
              <div className="flex justify-between items-center mb-2">
                <span 
                  className="text-sm font-medium"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {bulkFiles.length} file{bulkFiles.length !== 1 ? 's' : ''} selected
                </span>
                <button
                  onClick={clearAllFiles}
                  className="text-xs px-2 py-1 rounded hover:bg-opacity-80"
                  style={{ 
                    color: 'var(--color-error)',
                    backgroundColor: 'var(--color-bg-tertiary)',
                  }}
                >
                  Clear all
                </button>
              </div>
              <div 
                className="max-h-32 overflow-y-auto rounded border"
                style={{ 
                  borderColor: 'var(--color-border)',
                  backgroundColor: 'var(--color-bg-primary)',
                }}
              >
                {bulkFiles.map((file, index) => (
                  <div 
                    key={`${file.name}-${index}`}
                    className="flex justify-between items-center px-3 py-1.5 text-sm border-b last:border-b-0"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
                    <span 
                      className="truncate flex-1"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      {file.name}
                    </span>
                    <button
                      onClick={() => removeFile(index)}
                      className="ml-2 text-xs px-1.5 py-0.5 rounded transition-colors"
                      style={{ color: 'var(--color-text-muted)' }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
                        e.currentTarget.style.color = 'var(--color-error)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent'
                        e.currentTarget.style.color = 'var(--color-text-muted)'
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
