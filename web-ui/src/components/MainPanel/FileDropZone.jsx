import { useRef } from 'react'
import { formatFileSize } from '../../utils/formatters'

/**
 * File drop zone component for drag-and-drop file uploads
 */
export default function FileDropZone({
  file,
  isDragging,
  error,
  onDragEnter,
  onDragLeave,
  onDragOver,
  onDrop,
  onFileSelect,
  onClear,
  disabled,
}) {
  const inputRef = useRef(null)

  const handleClick = () => {
    if (!disabled && inputRef.current) {
      inputRef.current.click()
    }
  }

  return (
    <div>
      <div
        onClick={handleClick}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDragOver={onDragOver}
        onDrop={onDrop}
        className={`
          relative rounded-lg border-2 border-dashed p-8 text-center transition-all cursor-pointer
          ${isDragging ? 'active' : ''}
        `}
        style={{
          borderColor: isDragging 
            ? 'var(--color-accent)' 
            : error 
              ? 'var(--color-error)' 
              : 'var(--color-border)',
          backgroundColor: isDragging 
            ? 'var(--color-info-bg)' 
            : 'var(--color-bg-primary)',
          opacity: disabled ? 0.6 : 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        <input
          ref={inputRef}
          type="file"
          onChange={onFileSelect}
          accept=".pdf,.txt,.tex,.latex,.bib"
          className="hidden"
          disabled={disabled}
        />

        {file ? (
          <div className="space-y-2">
            <div className="flex items-center justify-center gap-2">
              <svg 
                className="w-8 h-8" 
                fill="none" 
                viewBox="0 0 24 24" 
                stroke="currentColor"
                style={{ color: 'var(--color-success)' }}
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span 
                className="font-medium"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {file.name}
              </span>
            </div>
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {formatFileSize(file.size)}
            </p>
            {!disabled && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onClear()
                }}
                className="text-sm underline transition-colors"
                style={{ color: 'var(--color-accent)' }}
              >
                Choose different file
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <svg 
              className="w-12 h-12 mx-auto" 
              fill="none" 
              viewBox="0 0 24 24" 
              stroke="currentColor"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p style={{ color: 'var(--color-text-primary)' }}>
              <span 
                className="font-medium"
                style={{ color: 'var(--color-accent)' }}
              >
                Click to upload
              </span>
              {' '}or drag and drop
            </p>
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-muted)' }}
            >
              PDF, TXT, TEX, LaTeX, or BibTeX (max 200MB)
            </p>
          </div>
        )}
      </div>

      {/* Error message */}
      {error && (
        <p 
          className="mt-2 text-sm"
          style={{ color: 'var(--color-error)' }}
        >
          {error}
        </p>
      )}
    </div>
  )
}
