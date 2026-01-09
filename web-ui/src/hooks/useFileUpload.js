import { useState, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'
import { formatFileSize } from '../utils/formatters'

const MAX_FILE_SIZE = 200 * 1024 * 1024 // 200MB
const ALLOWED_TYPES = [
  'application/pdf',
  'text/plain',
  'text/x-tex',
  'application/x-tex',
  'application/x-latex',
]
const ALLOWED_EXTENSIONS = ['.pdf', '.txt', '.tex', '.latex', '.bib']

/**
 * Hook for file upload with drag-and-drop support
 * @returns {object} File upload state and handlers
 */
export function useFileUpload() {
  const [file, setFile] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [error, setError] = useState(null)
  const dragCounterRef = useRef(0)

  const validateFile = useCallback((file) => {
    // Check size
    if (file.size > MAX_FILE_SIZE) {
      const msg = `File too large. Maximum size is ${formatFileSize(MAX_FILE_SIZE)}, got ${formatFileSize(file.size)}`
      logger.warn('useFileUpload', msg)
      return msg
    }

    // Check extension
    const fileName = file.name.toLowerCase()
    const hasValidExtension = ALLOWED_EXTENSIONS.some(ext => fileName.endsWith(ext))
    
    // Check MIME type (be lenient since some systems don't set it correctly)
    const hasValidType = ALLOWED_TYPES.includes(file.type) || file.type === ''
    
    if (!hasValidExtension && !hasValidType) {
      const msg = `Invalid file type. Allowed: PDF, TXT, TEX, LaTeX, BibTeX`
      logger.warn('useFileUpload', msg)
      return msg
    }

    return null
  }, [])

  const handleFile = useCallback((file) => {
    setError(null)
    
    const validationError = validateFile(file)
    if (validationError) {
      setError(validationError)
      return false
    }

    logger.info('useFileUpload', `File selected: ${file.name} (${formatFileSize(file.size)})`)
    setFile(file)
    return true
  }, [validateFile])

  const handleDragEnter = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounterRef.current++
    
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true)
    }
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounterRef.current--
    
    if (dragCounterRef.current === 0) {
      setIsDragging(false)
    }
  }, [])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    dragCounterRef.current = 0

    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      handleFile(files[0])
    }
  }, [handleFile])

  const handleInputChange = useCallback((e) => {
    const files = e.target.files
    if (files && files.length > 0) {
      handleFile(files[0])
    }
  }, [handleFile])

  const clearFile = useCallback(() => {
    logger.debug('useFileUpload', 'File cleared')
    setFile(null)
    setError(null)
  }, [])

  return {
    file,
    isDragging,
    error,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    handleInputChange,
    clearFile,
    maxFileSize: MAX_FILE_SIZE,
    allowedExtensions: ALLOWED_EXTENSIONS,
  }
}
