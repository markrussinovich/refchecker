import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useConfigStore } from '../../stores/useConfigStore'
import { useAuthStore } from '../../stores/useAuthStore'
import { useKeyStore } from '../../stores/useKeyStore'
import LLMConfigModal from './LLMConfigModal'
import { logger } from '../../utils/logger'

/**
 * LLM configuration selector with dropdown
 * @param {Object} props
 * @param {string} props.mode - extraction or hallucination
 */
export default function LLMSelector({ mode = 'extraction' }) {
  const {
    configs,
    selectedConfigId,
    selectedExtractionConfigId,
    selectedHallucinationConfigId,
    selectConfig,
    selectExtractionConfig,
    selectHallucinationConfig,
    deleteConfig,
    isLoading,
  } = useConfigStore()
  const multiuser = useAuthStore(state => state.multiuser)
  const hasKeyInBrowser = useKeyStore(state => state.hasKey)
  const hallucinationCapableProviders = ['openai', 'anthropic', 'google', 'azure']
  const isHallucinationMode = mode === 'hallucination'
  const visibleConfigs = isHallucinationMode
    ? configs.filter(config => hallucinationCapableProviders.includes(config.provider))
    : configs
  const activeSelectedId = isHallucinationMode
    ? selectedHallucinationConfigId
    : (selectedExtractionConfigId || selectedConfigId)

  // A config is "valid" (selectable) if it has a key:
  //   single-user: has_key flag from DB
  //   multi-user: the current tab has a key for that provider
  const configHasKey = (config) => {
    if (!config) return false
    if (config.provider === 'vllm') return true
    if (hasKeyInBrowser(`llm:${config.id}`)) return true
    if (hasKeyInBrowser(config.provider)) return true
    if (multiuser) return false
    return !!config.has_key || configs.some(existing => (
      existing.provider === config.provider && existing.has_key
    ))
  }
  const [isOpen, setIsOpen] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [editConfig, setEditConfig] = useState(null)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState(null)
  const [menuStyle, setMenuStyle] = useState(null)
  const dropdownRef = useRef(null)

  const selectedConfig = visibleConfigs.find(c => c.id === activeSelectedId && configHasKey(c))

  // Format display name as provider-model
  const formatConfigName = (config) => {
    if (!config) return 'No LLM configured'
    return config.name || `${config.provider}-${config.model || 'default'}`
  }

  // Find a keyless config for the same provider to use as prefill when creating new configs
  const findPrefillConfig = () => {
    const keylessConfigs = visibleConfigs.filter(c => !configHasKey(c))
    return keylessConfigs.length > 0 ? keylessConfigs[0] : null
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false)
        setConfirmingDeleteId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (!isOpen) return undefined

    const updateMenuPosition = () => {
      const rect = dropdownRef.current?.getBoundingClientRect()
      if (!rect) return

      const viewportPadding = 16
      const availableBelow = window.innerHeight - rect.bottom - viewportPadding
      const availableAbove = rect.top - viewportPadding
      const menuMaxHeight = Math.min(320, Math.max(180, Math.max(availableBelow, availableAbove)))
      const openAbove = availableBelow < 220 && availableAbove > availableBelow

      setMenuStyle({
        position: 'fixed',
        left: `${rect.left}px`,
        top: openAbove ? 'auto' : `${rect.bottom + 4}px`,
        bottom: openAbove ? `${window.innerHeight - rect.top + 4}px` : 'auto',
        width: `${rect.width}px`,
        maxHeight: `${menuMaxHeight}px`,
        zIndex: 1000,
      })
    }

    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [isOpen])

  const handleSelect = (config) => {
    if (!configHasKey(config)) {
      setEditConfig(config)
      setShowModal(true)
      setIsOpen(false)
      return
    }
    logger.info('LLMSelector', `Selected config ${config.id}`)
    if (isHallucinationMode) {
      selectHallucinationConfig(config.id)
    } else if (selectExtractionConfig) {
      selectExtractionConfig(config.id)
    } else {
      selectConfig(config.id)
    }
    setIsOpen(false)
  }

  const handleDeleteClick = (e, id) => {
    e.stopPropagation()
    setConfirmingDeleteId(id)
  }

  const handleConfirmDelete = async (e, id) => {
    e.stopPropagation()
    try {
      await deleteConfig(id)
      logger.info('LLMSelector', `Deleted config ${id}`)
    } catch (error) {
      logger.error('LLMSelector', 'Failed to delete config', error)
    }
    setConfirmingDeleteId(null)
  }

  const handleCancelDelete = (e) => {
    e.stopPropagation()
    setConfirmingDeleteId(null)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Dropdown trigger */}
      <button
        onClick={() => {
          setIsOpen(!isOpen)
          setConfirmingDeleteId(null)
        }}
        className="w-full flex items-center justify-between px-3 py-2 rounded-lg border transition-colors cursor-pointer"
        style={{
          backgroundColor: 'var(--color-bg-primary)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-primary)',
        }}
        disabled={isLoading}
      >
        <span className="truncate">
          {selectedConfig ? (
            <span className="font-medium">{formatConfigName(selectedConfig)}</span>
          ) : (
            <span style={{ color: 'var(--color-text-muted)' }}>
              {isLoading ? 'Loading...' : 'No LLM configured'}
            </span>
          )}
        </span>
        <svg 
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none" 
          viewBox="0 0 24 24" 
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown menu */}
      {isOpen && menuStyle && createPortal((
        <div 
          className="rounded-lg border shadow-lg overflow-hidden"
          onMouseDown={(event) => event.stopPropagation()}
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            borderColor: 'var(--color-border)',
            ...menuStyle,
          }}
        >
          {/* Existing configs */}
          <div className="overflow-y-auto" style={{ maxHeight: `calc(${menuStyle.maxHeight} - 41px)` }}>
            {visibleConfigs.length === 0 ? (
              <div 
                className="px-3 py-2 text-sm"
                style={{ color: 'var(--color-text-muted)' }}
              >
                {isHallucinationMode ? 'No hallucination-capable configurations' : 'No configurations'}
              </div>
            ) : (
              visibleConfigs.map(config => {
                const selectable = configHasKey(config)
                return (
                <div
                  key={config.id}
                  className="flex items-center justify-between px-3 py-2 cursor-pointer transition-colors"
                  style={{
                    backgroundColor: config.id === activeSelectedId 
                      ? 'var(--color-bg-tertiary)' 
                      : 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (config.id !== activeSelectedId) {
                      e.currentTarget.style.backgroundColor = 'var(--color-bg-secondary)'
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (config.id !== activeSelectedId) {
                      e.currentTarget.style.backgroundColor = 'transparent'
                    }
                  }}
                >
                  <div 
                    className="flex-1 min-w-0"
                    onClick={() => handleSelect(config)}
                  >
                    <div 
                      className="font-medium truncate"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      {formatConfigName(config)}
                    </div>
                    <div 
                      className="text-xs truncate"
                      style={{ color: 'var(--color-text-muted)' }}
                    >
                      {config.provider}{config.model ? ` / ${config.model}` : ''}
                      {!selectable ? ' / key needed' : ''}
                      {config.provider === 'vllm' ? ' / extraction only' : ''}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {confirmingDeleteId === config.id ? (
                      <div
                        className="flex items-center gap-1 px-1 py-0.5 rounded-lg"
                        style={{ backgroundColor: 'var(--color-error-bg)' }}
                      >
                        <button
                          onClick={(e) => handleConfirmDelete(e, config.id)}
                          className="p-1 rounded transition-colors"
                          style={{ color: 'var(--color-error)' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'var(--color-error)'
                            e.currentTarget.style.color = 'white'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent'
                            e.currentTarget.style.color = 'var(--color-error)'
                          }}
                          title="Confirm delete"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        </button>
                        <button
                          onClick={handleCancelDelete}
                          className="p-1 rounded transition-colors"
                          style={{ color: 'var(--color-text-secondary)' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'var(--color-bg-tertiary)'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent'
                          }}
                          title="Cancel"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditConfig(config)
                            setShowModal(true)
                            setIsOpen(false)
                          }}
                          className="p-1 rounded transition-colors cursor-pointer"
                          style={{ color: 'var(--color-text-secondary)' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'var(--color-accent)'
                            e.currentTarget.style.color = 'white'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent'
                            e.currentTarget.style.color = 'var(--color-text-secondary)'
                          }}
                          title="Edit configuration"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                        <button
                          onClick={(e) => handleDeleteClick(e, config.id)}
                          className="p-1 rounded transition-colors cursor-pointer"
                          style={{ color: 'var(--color-error)' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'var(--color-error-bg)'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent'
                          }}
                          title="Delete configuration"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </>
                    )}
                  </div>
                </div>
                )
              })
            )}
          </div>

          {/* Add new config button */}
          <div 
            className="border-t"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <button
              onClick={() => {
                setIsOpen(false)
                setEditConfig(null)
                setShowModal(true)
              }}
              className="w-full flex items-center px-3 py-2 text-sm transition-colors cursor-pointer"
              style={{ color: 'var(--color-accent)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--color-bg-secondary)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add LLM Configuration
            </button>
          </div>
        </div>
      ), document.body)}

      {/* Add/Edit Modal */}
      <LLMConfigModal 
        isOpen={showModal} 
        onClose={() => {
          setShowModal(false)
          setEditConfig(null)
        }}
        editConfig={editConfig}
        prefillConfig={!editConfig ? findPrefillConfig() : null}
      />
    </div>
  )
}
