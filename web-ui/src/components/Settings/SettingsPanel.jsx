import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { useKeyStore } from '../../stores/useKeyStore'
import { useAuthStore } from '../../stores/useAuthStore'
import LLMSelector from '../Sidebar/LLMSelector'
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
    updateSetting,
    fetchSettings
  } = useSettingsStore()
  const panelRef = useRef(null)
  const [activeSection, setActiveSection] = useState('General')

  // Key store for Semantic Scholar API key management
  const { hasKey, setKey, deleteKey } = useKeyStore()
  const multiuser = useAuthStore(state => state.multiuser)
  
  // Semantic Scholar API key state
  const [ssIsEditing, setSsIsEditing] = useState(false)
  const [ssApiKey, setSsApiKey] = useState('')
  const [ssIsSaving, setSsIsSaving] = useState(false)
  const [ssIsValidating, setSsIsValidating] = useState(false)
  const [ssError, setSsError] = useState(null)
  const [ssServerHasKey, setSsServerHasKey] = useState(false)
  const ssHasKey = hasKey('semantic_scholar') || ssServerHasKey

  // Local DB path state
  const [dbPathLocal, setDbPathLocal] = useState(settings.db_path?.value || '')
  const [dbPathError, setDbPathError] = useState(null)
  const [dbPathSuccess, setDbPathSuccess] = useState(null)
  const [dbPathSaving, setDbPathSaving] = useState(false)

  // Cache directory state
  const [cacheDirLocal, setCacheDirLocal] = useState(settings.cache_dir?.value || '')
  const [cacheDirError, setCacheDirError] = useState(null)
  const [cacheDirSuccess, setCacheDirSuccess] = useState(null)
  const [cacheDirSaving, setCacheDirSaving] = useState(false)

  // Sync local db path when settings are fetched from the server
  useEffect(() => {
    if (settings.db_path?.value !== undefined) {
      setDbPathLocal(settings.db_path.value)
    }
  }, [settings.db_path?.value])

  // Sync cache dir when settings are fetched from the server
  useEffect(() => {
    if (settings.cache_dir?.value !== undefined) {
      setCacheDirLocal(settings.cache_dir.value)
    }
  }, [settings.cache_dir?.value])

  const handleDbPathSave = async () => {
    setDbPathError(null)
    setDbPathSuccess(null)
    setDbPathSaving(true)
    try {
      const response = await fetch('/api/settings/db_path', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: dbPathLocal }),
      })
      const result = await response.json()
      if (!response.ok) {
        setDbPathError(result.detail || 'Failed to save')
      } else {
        setDbPathSuccess(result.message || 'Saved')
        fetchSettings()
      }
    } catch (err) {
      setDbPathError(err.message || 'Failed to save')
    } finally {
      setDbPathSaving(false)
    }
  }

  const handleCacheDirSave = async () => {
    setCacheDirError(null)
    setCacheDirSuccess(null)
    setCacheDirSaving(true)
    try {
      const response = await fetch('/api/settings/cache_dir', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: cacheDirLocal }),
      })
      const result = await response.json()
      if (!response.ok) {
        setCacheDirError(result.detail || 'Failed to save')
      } else {
        setCacheDirSuccess(result.message || 'Saved')
        updateSetting('cache_dir', cacheDirLocal)
      }
    } catch (err) {
      setCacheDirError(err.message || 'Failed to save')
    } finally {
      setCacheDirSaving(false)
    }
  }

  // Load SS key status from server on mount
  useEffect(() => {
    api.getSemanticScholarKeyStatus().then(res => {
      setSsServerHasKey(res.data.has_key)
    }).catch(() => {})
  }, [])

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

  // Semantic Scholar API key handlers: browser cache in multi-user, database in single-user.
  const handleSsSave = async () => {
    if (!ssApiKey.trim()) {
      setSsError('API key cannot be empty')
      return
    }
    try {
      setSsIsSaving(true)
      setSsIsValidating(true)
      setSsError(null)

      const validationResponse = await api.validateSemanticScholarKey(ssApiKey.trim())

      if (!validationResponse.data.valid) {
        setSsError(validationResponse.data.message || 'Invalid API key')
        setSsIsValidating(false)
        return
      }

      if (multiuser) {
        setKey('semantic_scholar', ssApiKey.trim())
        setSsServerHasKey(false)
        logger.info('SettingsPanel', 'SS API key saved to browser key cache')
      } else {
        await api.setSemanticScholarKey(ssApiKey.trim())
        deleteKey('semantic_scholar')
        setSsServerHasKey(true)
        logger.info('SettingsPanel', 'SS API key saved to local database')
      }
      setSsIsValidating(false)
      setSsIsEditing(false)
      setSsApiKey('')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to save SS key', err)
      setSsError(err.response?.data?.detail || 'Failed to save API key')
    } finally {
      setSsIsValidating(false)
      setSsIsSaving(false)
    }
  }

  const handleSsDelete = async () => {
    setSsIsSaving(true)
    try {
      if (multiuser) {
        deleteKey('semantic_scholar')
        setSsServerHasKey(false)
      } else {
        await api.deleteSemanticScholarKey()
        deleteKey('semantic_scholar')
        setSsServerHasKey(false)
      }
      setSsIsEditing(false)
      setSsApiKey('')
      setSsError(null)
      logger.info('SettingsPanel', 'SS API key removed')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to delete SS key', err)
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
    { id: 'LLM', label: 'LLM', icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.75h4.5M9.75 20.25h4.5M6.75 7.5h10.5a2.25 2.25 0 012.25 2.25v4.5a2.25 2.25 0 01-2.25 2.25H6.75a2.25 2.25 0 01-2.25-2.25v-4.5A2.25 2.25 0 016.75 7.5z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h.01M15 12h.01" />
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

      {/* Concurrency Setting (single-user only) */}
      {!multiuser && (
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
            width: '80px',
          }}
        />
      </div>
      )}

      {/* Local Database Directory (single-user only, rendered when setting exists in API response) */}
      {settings.db_path && !multiuser && (
        <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="mb-2">
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {settings.db_path.label || 'Local Database'}
            </div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              {settings.db_path.description}
            </div>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={dbPathLocal}
              placeholder="/path/to/local-databases"
              onChange={(e) => { setDbPathLocal(e.target.value); setDbPathError(null); setDbPathSuccess(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleDbPathSave() }}
              className="flex-1 px-3 py-2 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: dbPathError ? 'var(--color-error, #ef4444)' : 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
            <button
              onClick={handleDbPathSave}
              disabled={dbPathSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{
                backgroundColor: 'var(--color-accent, #3b82f6)',
                color: 'white',
                opacity: dbPathSaving ? 0.6 : 1,
              }}
            >
              {dbPathSaving ? '...' : 'Save'}
            </button>
          </div>
          {dbPathError && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-error, #ef4444)' }}>{dbPathError}</div>
          )}
          {dbPathSuccess && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-success, #22c55e)' }}>{dbPathSuccess}</div>
          )}
          {settings.db_path?.value && settings.db_path?.current_snapshot && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Current Semantic Scholar snapshot: {settings.db_path.current_snapshot}
            </div>
          )}
        </div>
      )}

      {/* Cache Directory (single-user only) */}
      {settings.cache_dir && !multiuser && (
        <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="mb-2">
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {settings.cache_dir.label || 'Cache Directory'}
            </div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              {settings.cache_dir.description}
            </div>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={cacheDirLocal}
              placeholder="/path/to/cache"
              onChange={(e) => { setCacheDirLocal(e.target.value); setCacheDirError(null); setCacheDirSuccess(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCacheDirSave() }}
              className="flex-1 px-3 py-2 rounded-lg border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: cacheDirError ? 'var(--color-error, #ef4444)' : 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            />
            <button
              onClick={handleCacheDirSave}
              disabled={cacheDirSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{
                backgroundColor: 'var(--color-accent, #3b82f6)',
                color: 'white',
                opacity: cacheDirSaving ? 0.6 : 1,
              }}
            >
              {cacheDirSaving ? '...' : 'Save'}
            </button>
          </div>
          {cacheDirError && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-error, #ef4444)' }}>{cacheDirError}</div>
          )}
          {cacheDirSuccess && (
            <div className="text-xs mt-1" style={{ color: 'var(--color-success, #22c55e)' }}>{cacheDirSuccess}</div>
          )}
        </div>
      )}
    </div>
  )

  const renderLLMSection = () => (
    <div className="space-y-4">
      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
          Configured LLMs
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          Both selectors use the same configured LLM list. Add, edit, and remove configurations from either selector.
        </div>
      </div>

      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
          Extraction LLM
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          Used to extract references from PDFs, URLs, and pasted text. Local vLLM is available for extraction in single-user local deployments.
        </div>
        <div className="mt-3 max-w-sm">
          <LLMSelector mode="extraction" />
        </div>
      </div>

      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
          Hallucination LLM
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          Used for hallucination checks that require web-capable providers: OpenAI, Google, Anthropic, or Azure OpenAI.
        </div>
        <div className="mt-3 max-w-sm">
          <LLMSelector mode="hallucination" />
        </div>
      </div>

      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
          Key Storage
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          {multiuser
            ? 'Multi-user web UI keys are retrieved from this encrypted browser cache for the local web interface and are not stored in the local database or on the server.'
            : 'Local web UI keys are encrypted in the local RefChecker database.'}
        </div>
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
            {multiuser && (
              <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                Encrypted in this browser cache for the local web interface and not saved on the server.
              </div>
            )}
          </div>
          {!ssIsEditing && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSsIsEditing(true)}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{ color: 'var(--color-accent)' }}
              >
                {ssHasKey ? 'Edit' : 'Set'}
              </button>
              {ssHasKey && (
                <button
                  onClick={handleSsDelete}
                  disabled={ssIsSaving}
                  className="text-xs px-2 py-1 rounded cursor-pointer"
                  style={{ color: 'var(--color-error)' }}
                >
                  Remove
                </button>
              )}
            </div>
          )}
        </div>
        
        {ssIsEditing && (
          <div className="mt-2 space-y-2">
            <div className="flex gap-2">
              <input
                type="password"
                value={ssApiKey}
                onChange={(e) => setSsApiKey(e.target.value)}
                placeholder="Enter API key…"
                className="flex-1 px-2 py-1.5 text-sm rounded border"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: ssError ? 'var(--color-error)' : 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                disabled={ssIsSaving || ssIsValidating}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && ssApiKey.trim()) handleSsSave()
                  if (e.key === 'Escape') handleSsCancel()
                }}
              />
              <button
                onClick={handleSsSave}
                disabled={ssIsSaving || ssIsValidating || !ssApiKey.trim()}
                className="px-3 py-1.5 text-xs rounded cursor-pointer"
                style={{ backgroundColor: 'var(--color-accent)', color: 'white', opacity: ssIsSaving || ssIsValidating || !ssApiKey.trim() ? 0.5 : 1 }}
              >
                {ssIsValidating ? '…' : ssIsSaving ? '…' : 'Save'}
              </button>
              <button
                onClick={handleSsCancel}
                disabled={ssIsSaving || ssIsValidating}
                className="px-3 py-1.5 text-xs rounded border cursor-pointer"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
            </div>
            {ssError && (
              <div className="text-xs" style={{ color: 'var(--color-error)' }}>
                {ssError}
              </div>
            )}
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
          height: '620px',
          maxHeight: '95vh',
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
                {activeSection === 'LLM' && renderLLMSection()}
                {activeSection === 'API Keys' && renderAPIKeysSection()}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
