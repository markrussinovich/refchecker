import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFileUpload } from './useFileUpload'

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('should initialize with no file and not dragging', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(result.current.file).toBeNull()
    expect(result.current.isDragging).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('should have handleDragEnter method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.handleDragEnter).toBe('function')
  })

  it('should have handleDragLeave method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.handleDragLeave).toBe('function')
  })

  it('should have handleDragOver method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.handleDragOver).toBe('function')
  })

  it('should have handleDrop method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.handleDrop).toBe('function')
  })

  it('should have handleInputChange method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.handleInputChange).toBe('function')
  })

  it('should have clearFile method', () => {
    const { result } = renderHook(() => useFileUpload())
    
    expect(typeof result.current.clearFile).toBe('function')
  })

  it('should set isDragging on drag enter', () => {
    const { result } = renderHook(() => useFileUpload())
    
    const mockEvent = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: {
        items: ['file1'],
      },
    }
    
    act(() => {
      result.current.handleDragEnter(mockEvent)
    })
    
    expect(result.current.isDragging).toBe(true)
    expect(mockEvent.preventDefault).toHaveBeenCalled()
  })

  it('should clear isDragging on drag leave', () => {
    const { result } = renderHook(() => useFileUpload())
    
    const mockEnterEvent = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: {
        items: ['file1'],
      },
    }
    
    const mockLeaveEvent = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    }
    
    // First set dragging
    act(() => {
      result.current.handleDragEnter(mockEnterEvent)
    })
    expect(result.current.isDragging).toBe(true)
    
    // Then leave
    act(() => {
      result.current.handleDragLeave(mockLeaveEvent)
    })
    expect(result.current.isDragging).toBe(false)
  })

  it('should clear file and error with clearFile', () => {
    const { result } = renderHook(() => useFileUpload())
    
    act(() => {
      result.current.clearFile()
    })
    
    expect(result.current.file).toBeNull()
    expect(result.current.error).toBeNull()
  })
})
