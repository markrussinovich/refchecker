import { useEffect, useRef } from 'react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { logger } from '../../utils/logger'

/**
 * Settings panel component - opens as a modal overlay
 * Designed for extensibility with sections for different setting categories
 */
export default function SettingsPanel() {
  const { 
    settings, 
    isLoading, 
    isSettingsOpen, 
    closeSettings, 
    updateSetting 
  } = useSettingsStore()
  const panelRef = useRef(null)

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
      // Delay to prevent immediate close from the gear icon click
      setTimeout(() => {
        document.addEventListener('mousedown', handleClickOutside)
      }, 100)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isSettingsOpen, closeSettings])

  if (!isSettingsOpen) return null

  // Group settings by section
  const sections = {}
  Object.entries(settings).forEach(([key, setting]) => {
    const section = setting.section || 'General'
    if (!sections[section]) {
      sections[section] = []
    }
    sections[section].push({ key, ...setting })
  })

  const handleSettingChange = (key, value) => {
    logger.info('SettingsPanel', `Updating setting ${key} to ${value}`)
    updateSetting(key, value)
  }

  const renderSettingInput = (setting) => {
    const { key, value, type, min, max, label, description } = setting

    switch (type) {
      case 'number':
        return (
          <div key={key} className="mb-4">
            <label className="block mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
              <span className="font-medium text-sm">{label}</span>
              {description && (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                  {description}
                </p>
              )}
            </label>
            <input
              type="number"
              value={value}
              min={min}
              max={max}
              onChange={(e) => handleSettingChange(key, e.target.value)}
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
        )

      case 'boolean':
        return (
          <div key={key} className="mb-4 flex items-start gap-3">
            <label className="relative inline-flex items-center cursor-pointer mt-0.5">
              <input
                type="checkbox"
                checked={value === 'true'}
                onChange={(e) => handleSettingChange(key, e.target.checked ? 'true' : 'false')}
                className="sr-only peer"
              />
              <div 
                className="w-9 h-5 rounded-full peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-offset-2 after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-4"
                style={{
                  backgroundColor: value === 'true' ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              />
            </label>
            <div>
              <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>{label}</span>
              {description && (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                  {description}
                </p>
              )}
            </div>
          </div>
        )

      case 'string':
      default:
        return (
          <div key={key} className="mb-4">
            <label className="block mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
              <span className="font-medium text-sm">{label}</span>
              {description && (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                  {description}
                </p>
              )}
            </label>
            <input
              type="text"
              value={value}
              onChange={(e) => handleSettingChange(key, e.target.value)}
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)'
              }}
            />
          </div>
        )
    }
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
    >
      <div
        ref={panelRef}
        className="rounded-lg shadow-xl max-w-md w-full max-h-[80vh] overflow-hidden flex flex-col"
        style={{ backgroundColor: 'var(--color-bg-secondary)' }}
      >
        {/* Header */}
        <div 
          className="px-6 py-4 border-b flex items-center justify-between"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Settings
          </h2>
          <button
            onClick={closeSettings}
            className="p-1 rounded-md transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <svg className="animate-spin h-6 w-6" style={{ color: 'var(--color-accent)' }} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </div>
          ) : (
            <>
              {Object.entries(sections).map(([sectionName, sectionSettings]) => (
                <div key={sectionName} className="mb-6 last:mb-0">
                  <h3 
                    className="text-xs font-semibold uppercase tracking-wide mb-3"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {sectionName}
                  </h3>
                  {sectionSettings.map(renderSettingInput)}
                </div>
              ))}
              
              {Object.keys(sections).length === 0 && (
                <p className="text-center py-4" style={{ color: 'var(--color-text-secondary)' }}>
                  No settings available
                </p>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div 
          className="px-6 py-3 border-t text-xs"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          Settings are saved automatically
        </div>
      </div>
    </div>
  )
}
