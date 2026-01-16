import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'

/**
 * Settings panel component - ChatGPT-style with left navigation
 */
export default function SettingsPanel({ theme, onThemeChange }) {
  const { 
    settings, 
    isLoading, 
    version,
    isSettingsOpen, 
    closeSettings, 
    updateSetting 
  } = useSettingsStore()
  const panelRef = useRef(null)
  const [activeSection, setActiveSection] = useState('General')
  
  // Semantic Scholar API key state
  const [ssHasKey, setSsHasKey] = useState(false)
  const [ssIsEditing, setSsIsEditing] = useState(false)
  const [ssApiKey, setSsApiKey] = useState('')
  const [ssIsLoading, setSsIsLoading] = useState(true)
  const [ssIsSaving, setSsIsSaving] = useState(false)
  const [ssIsValidating, setSsIsValidating] = useState(false)
  const [ssError, setSsError] = useState(null)

  // Load Semantic Scholar key status when panel opens
  useEffect(() => {
    if (isSettingsOpen && activeSection === 'API Keys') {
      loadSsKeyStatus()
    }
  }, [isSettingsOpen, activeSection])

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && isSettingsOpen) {
        closeSettings()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isSettingsOpen, closeSettings])

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        closeSettings()
      }
    }
    if (isSettingsOpen) {
      setTimeout(() => {
        document.addEventListener('mousedown', handleClickOutside)
      }, 100)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isSettingsOpen, closeSettings])

  if (!isSettingsOpen) return null

  const handleSettingChange = (key, value) => {
    logger.info('SettingsPanel', `Updating setting ${key} to ${value}`)
    updateSetting(key, value)
  }

  // Semantic Scholar API key handlers
  const loadSsKeyStatus = async () => {
    try {
      setSsIsLoading(true)
      const response = await api.getSemanticScholarKeyStatus()
      setSsHasKey(response.data.has_key)
      logger.info('SettingsPanel', `SS Key status: ${response.data.has_key ? 'configured' : 'not configured'}`)
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to load SS key status', err)
      setSsError('Failed to load status')
    } finally {
      setSsIsLoading(false)
    }
  }

  const handleSsSave = async () => {
    if (!ssApiKey.trim()) {
      setSsError('API key cannot be empty')
      return
    }
    try {
      // First validate the API key
      setSsIsValidating(true)
      setSsError(null)
      
      const validationResponse = await api.validateSemanticScholarKey(ssApiKey.trim())
      
      if (!validationResponse.data.valid) {
        setSsError(validationResponse.data.message || 'Invalid API key')
        setSsIsValidating(false)
        return
      }
      
      logger.info('SettingsPanel', 'SS API key validated successfully')
      setSsIsValidating(false)
      
      // Now save the key
      setSsIsSaving(true)
      await api.setSemanticScholarKey(ssApiKey.trim())
      setSsHasKey(true)
      setSsIsEditing(false)
      setSsApiKey('')
      logger.info('SettingsPanel', 'SS API key saved')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to save SS key', err)
      setSsError(err.response?.data?.detail || 'Failed to validate API key')
    } finally {
      setSsIsValidating(false)
      setSsIsSaving(false)
    }
  }

  const handleSsDelete = async () => {
    try {
      setSsIsSaving(true)
      setSsError(null)
      await api.deleteSemanticScholarKey()
      setSsHasKey(false)
      setSsIsEditing(false)
      setSsApiKey('')
      logger.info('SettingsPanel', 'SS API key deleted')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to delete SS key', err)
      setSsError(err.response?.data?.detail || 'Failed to delete API key')
    } finally {
      setSsIsSaving(false)
    }
  }

  const handleSsCancel = () => {
    setSsIsEditing(false)
    setSsApiKey('')
    setSsError(null)
  }

  const navItems = [
    { id: 'General', label: 'General', icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )},
    { id: 'API Keys', label: 'API Keys', icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
      </svg>
    )},
  ]

  const renderGeneralSection = () => (
    <div className="space-y-1">
      {/* Theme Setting */}
      <div className="flex items-center justify-between py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div>
          <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Theme</div>
        </div>
        <div className="relative">
          <select
            value={theme}
            onChange={(e) => onThemeChange(e.target.value)}
            className="appearance-none px-4 py-2 pr-8 rounded-lg border text-sm cursor-pointer"
            style={{
              backgroundColor: 'var(--color-bg-primary)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-primary)',
              minWidth: '120px'
            }}
          >
            <option value="system">System</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
          <svg 
            className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none" 
            fill="none" 
            viewBox="0 0 24 24" 
            stroke="currentColor"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {/* Concurrency Setting */}
      <div className="flex items-center justify-between py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div>
          <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {settings.max_concurrent_checks?.label || 'Concurrent Checks'}
          </div>
          <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
            {settings.max_concurrent_checks?.description || 'Maximum number of references to check simultaneously'}
          </div>
        </div>
        <input
          type="number"
          value={settings.max_concurrent_checks?.value ?? 6}
          min={settings.max_concurrent_checks?.min ?? 1}
          max={settings.max_concurrent_checks?.max ?? 20}
          onChange={(e) => handleSettingChange('max_concurrent_checks', e.target.value)}
          className="px-3 py-2 rounded-lg border text-sm text-center"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-primary)',
            width: '80px'
          }}
        />
      </div>
    </div>
  )

  const renderAPIKeysSection = () => (
    <div className="space-y-1">
      {/* Semantic Scholar API Key */}
      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center justify-between mb-1">
          <div>
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Semantic Scholar API Key</div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              Optional. Increases rate limits for reference verification.
            </div>
          </div>
          {!ssIsEditing && (
            <div className="flex items-center gap-2">
              {ssHasKey ? (
                <span 
                  className="text-xs px-2 py-0.5 rounded"
                  style={{ 
                    backgroundColor: 'var(--color-success-bg)',
                    color: 'var(--color-success)'
                  }}
                >
                  ✓ Configured
                </span>
              ) : (
                <span 
                  className="text-xs"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Not configured
                </span>
              )}
              <button
                onClick={() => setSsIsEditing(true)}
                className="text-sm px-3 py-1 rounded transition-colors cursor-pointer"
                style={{ color: 'var(--color-accent)' }}
              >
                {ssHasKey ? 'Edit' : 'Add'}
              </button>
            </div>
          )}
        </div>
        
        {ssIsLoading ? (
          <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
        ) : ssIsEditing && (
          <div className="mt-3 space-y-2">
            <input
              type="password"
              value={ssApiKey}
              onChange={(e) => setSsApiKey(e.target.value)}
              placeholder={ssHasKey ? "Enter new key..." : "Enter API key..."}
              className="w-full px-3 py-2 text-sm rounded border"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: ssError ? 'var(--color-error)' : 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
              disabled={ssIsSaving || ssIsValidating}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSsSave()
                if (e.key === 'Escape') handleSsCancel()
              }}
            />
            
            {ssError && (
              <div className="text-xs" style={{ color: 'var(--color-error)' }}>
                {ssError}
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={handleSsSave}
                disabled={ssIsSaving || ssIsValidating || !ssApiKey.trim()}
                className="px-4 py-1.5 text-sm rounded cursor-pointer"
                style={{
                  backgroundColor: 'var(--color-accent)',
                  color: 'white',
                  opacity: ssIsSaving || ssIsValidating || !ssApiKey.trim() ? 0.5 : 1,
                }}
              >
                {ssIsValidating ? 'Validating...' : ssIsSaving ? 'Saving...' : 'Save'}
              </button>
              {ssHasKey && (
                <button
                  onClick={handleSsDelete}
                  disabled={ssIsSaving || ssIsValidating}
                  className="px-4 py-1.5 text-sm rounded cursor-pointer"
                  style={{
                    backgroundColor: 'var(--color-error-bg)',
                    color: 'var(--color-error)',
                    opacity: ssIsSaving || ssIsValidating ? 0.5 : 1,
                  }}
                >
                  Delete
                </button>
              )}
              <button
                onClick={handleSsCancel}
                disabled={ssIsSaving || ssIsValidating}
                className="px-4 py-1.5 text-sm rounded border cursor-pointer"
                style={{
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
    >
      <div
        ref={panelRef}
        className="rounded-2xl shadow-2xl overflow-hidden flex"
        style={{ 
          backgroundColor: 'var(--color-bg-secondary)',
          width: '680px',
          maxWidth: '90vw',
          height: '400px',
          maxHeight: '80vh',
        }}
      >
        {/* Left Navigation */}
        <div 
          className="w-48 flex-shrink-0 border-r py-4"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
        >
          {/* Header with close */}
          <div className="px-4 mb-4 flex items-center gap-2">
            <button
              onClick={closeSettings}
              className="p-1.5 rounded-lg transition-colors cursor-pointer hover:bg-[var(--color-bg-tertiary)]"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <span className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>Settings</span>
          </div>
          
          {/* Nav items */}
          <nav className="space-y-1 px-3">
            {navItems.map(item => (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors cursor-pointer"
                style={{
                  backgroundColor: activeSection === item.id ? 'var(--color-bg-tertiary)' : 'transparent',
                  color: activeSection === item.id ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                }}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>

          <div className="px-4 mt-6 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Version {version || '—'}
          </div>
        </div>

        {/* Right Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-6 py-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
              {activeSection}
            </h2>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <svg className="animate-spin h-6 w-6" style={{ color: 'var(--color-accent)' }} fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
            ) : (
              <>
                {activeSection === 'General' && renderGeneralSection()}
                {activeSection === 'API Keys' && renderAPIKeysSection()}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
