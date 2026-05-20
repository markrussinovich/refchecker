import { useCallback, useRef, useState } from 'react'
import { fetchOpenReviewList } from '../../utils/api'

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
             ext.endsWith('.tex') || ext.endsWith('.latex') ||
             ext.endsWith('.bib') || ext.endsWith('.bbl') ||
             ext.endsWith('.docx') || ext.endsWith('.odt') ||
             ext.endsWith('.rtf') ||
             ext.endsWith('.md') || ext.endsWith('.markdown') ||
             ext.endsWith('.html') || ext.endsWith('.htm') ||
             ext.endsWith('.zip')
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
             ext.endsWith('.tex') || ext.endsWith('.latex') ||
             ext.endsWith('.bib') || ext.endsWith('.bbl') ||
             ext.endsWith('.docx') || ext.endsWith('.odt') ||
             ext.endsWith('.rtf') ||
             ext.endsWith('.md') || ext.endsWith('.markdown') ||
             ext.endsWith('.html') || ext.endsWith('.htm') ||
             ext.endsWith('.zip')
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

  // OpenReview venue scanner — wraps the CLI's --openreview flow.
  const [orVenue, setOrVenue] = useState('')
  const [orStatus, setOrStatus] = useState('accepted')
  const [orFetching, setOrFetching] = useState(false)
  const [orError, setOrError] = useState(null)
  const [orResult, setOrResult] = useState(null)
  const handleOpenReviewFetch = useCallback(async () => {
    setOrError(null); setOrResult(null)
    const venue = orVenue.trim()
    if (!venue) { setOrError('Enter a venue (e.g. iclr2024)'); return }
    setOrFetching(true)
    try {
      const res = await fetchOpenReviewList(venue, orStatus)
      const data = res.data
      const all = data.papers || []
      const limited = all.slice(0, 50) // existing batch endpoint cap
      setBulkUrls(limited.join('\n'))
      setOrResult({
        count: all.length,
        used: limited.length,
        display_name: data.display_name,
      })
    } catch (e) {
      setOrError(e.response?.data?.detail || e.message || 'Failed to fetch')
    } finally {
      setOrFetching(false)
    }
  }, [orVenue, orStatus, setBulkUrls])

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
          {/* OpenReview venue scanner — replaces the textarea with the
              fetched list (capped at 50, the batch limit). */}
          <div
            className="mb-3 p-3 rounded-lg border"
            style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}
          >
            <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
              Scan an OpenReview venue
            </div>
            <div className="flex gap-2 items-center flex-wrap">
              <input
                type="text"
                value={orVenue}
                onChange={(e) => setOrVenue(e.target.value)}
                placeholder="iclr2024, icml2025, aistats2025, uai2025, corl2025"
                disabled={disabled || orFetching}
                className="flex-1 px-3 py-1.5 rounded border text-xs font-mono"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                  minWidth: '180px',
                }}
              />
              <select
                value={orStatus}
                onChange={(e) => setOrStatus(e.target.value)}
                disabled={disabled || orFetching}
                className="px-2 py-1.5 rounded border text-xs"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              >
                <option value="accepted">accepted</option>
                <option value="submitted">submitted</option>
              </select>
              <button
                onClick={handleOpenReviewFetch}
                disabled={disabled || orFetching}
                className="px-3 py-1.5 rounded text-xs font-medium"
                style={{
                  backgroundColor: 'var(--color-accent, #3b82f6)',
                  color: 'white',
                  opacity: orFetching ? 0.6 : 1,
                }}
              >
                {orFetching ? 'Fetching…' : 'Fetch papers'}
              </button>
            </div>
            {orError && (
              <div className="text-xs mt-2" style={{ color: 'var(--color-error, #ef4444)' }}>{orError}</div>
            )}
            {orResult && (
              <div className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                {orResult.display_name}: fetched {orResult.count} papers,
                loaded {orResult.used} into the list below
                {orResult.count > orResult.used && (
                  <> (capped at 50 per batch — run multiple batches for full coverage)</>
                )}
                .
              </div>
            )}
          </div>

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
              accept=".pdf,.txt,.tex,.latex,.bib,.bbl,.docx,.odt,.rtf,.md,.markdown,.html,.htm,.zip"
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
                    className="flex justify-between items-center px-3 py-1.5 mr-1 text-sm border-b last:border-b-0"
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
                      className="ml-2 p-1 rounded transition-colors"
                      style={{ color: 'var(--color-text-muted)' }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
                        e.currentTarget.style.color = 'var(--color-error)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent'
                        e.currentTarget.style.color = 'var(--color-text-muted)'
                      }}
                      title="Remove file"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
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
