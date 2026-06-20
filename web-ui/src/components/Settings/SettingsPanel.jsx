import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { useKeyStore } from '../../stores/useKeyStore'
import { useAiDetectionStore } from '../../stores/useAiDetectionStore'
import { useAuthStore } from '../../stores/useAuthStore'
import LLMSelector from '../Sidebar/LLMSelector'
import * as api from '../../utils/api'
import { logger } from '../../utils/logger'
import { invokeTauri, isTauri, openExternal, getAppVersion } from '../../utils/tauriBridge'
import { collectDiagnostics, diagnosticsToText } from '../../utils/diagnostics'
import EnableAccountsForm from './EnableAccountsForm'

const REPO_URL = 'https://github.com/ArioMoniri/refchecker'
// Bug reports / feature requests go upstream to Mark Russinovich's repo;
// release downloads stay on this fork (where the desktop builds are published).
const ISSUES_URL = 'https://github.com/markrussinovich/refchecker'

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
    fetchSettings,
    initialSection,
  } = useSettingsStore()
  const panelRef = useRef(null)
  const [activeSection, setActiveSection] = useState('General')

  // Honor deep-links from the onboarding banner (and anywhere else that
  // calls openSettings(section)) by jumping to the requested pane.
  useEffect(() => {
    if (isSettingsOpen && initialSection) {
      setActiveSection(initialSection)
    }
  }, [isSettingsOpen, initialSection])

  // Key store for Semantic Scholar API key management
  const { hasKey, setKey, deleteKey } = useKeyStore()
  const multiuser = useAuthStore(state => state.multiuser)
  // Accounts / Teams section needs the full auth picture (single vs multi-user,
  // configured OAuth providers, and the signed-in user when there is one).
  const authRequired = useAuthStore(state => state.authRequired)
  const authProviders = useAuthStore(state => state.providers)
  const authUser = useAuthStore(state => state.user)
  const loginWithGoogle = useAuthStore(state => state.loginWithGoogle)
  const loginWithGithub = useAuthStore(state => state.loginWithGithub)
  const loginWithMicrosoft = useAuthStore(state => state.loginWithMicrosoft)
  const authLogout = useAuthStore(state => state.logout)

  // AI-generated-text detection (opt-in, client preference + local model mgmt)
  const aiDetection = useAiDetectionStore()
  const [aiDetKey, setAiDetKey] = useState('')
  const [aiDebugOpen, setAiDebugOpen] = useState(false)
  const [modelUpdate, setModelUpdate] = useState(null)  // { update_available, ... }
  useEffect(() => {
    if (isSettingsOpen && activeSection === 'AI Detection') {
      aiDetection.fetchModelStatus()
      aiDetection.fetchRuntimeStatus()
      // R61 — also load the multi-detector registry so the manager can list the
      // roster with real size/license/tier + per-detector install state.
      aiDetection.fetchDetectors()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSettingsOpen, activeSection])
  // Off the status-poll hot path: when the section opens and the model IS
  // installed, ask HF (once) whether a newer revision exists.
  useEffect(() => {
    if (isSettingsOpen && activeSection === 'AI Detection' && aiDetection.modelStatus?.installed) {
      api.checkAIDetectionModelUpdate()
        .then((r) => setModelUpdate(r?.data || null))
        .catch(() => setModelUpdate(null))
    }
  }, [isSettingsOpen, activeSection, aiDetection.modelStatus?.installed])
  
  // Semantic Scholar API key state
  const [ssIsEditing, setSsIsEditing] = useState(false)
  const [ssApiKey, setSsApiKey] = useState('')
  // Paperclip — same lifecycle as the SS key (Set / Edit / Remove).
  // Multi-user keeps it browser-only; single-user stores it locally so
  // the secondary tier auto-activates after restarts.
  const [pcApiKey, setPcApiKey] = useState('')
  const [pcIsEditing, setPcIsEditing] = useState(false)
  const [pcIsSaving, setPcIsSaving] = useState(false)
  const [pcError, setPcError] = useState(null)
  const [pcServerHasKey, setPcServerHasKey] = useState(false)
  const [ssIsSaving, setSsIsSaving] = useState(false)
  const [ssIsValidating, setSsIsValidating] = useState(false)
  const [ssError, setSsError] = useState(null)
  const [ssServerHasKey, setSsServerHasKey] = useState(false)
  const ssHasKey = hasKey('semantic_scholar') || ssServerHasKey
  const pcHasKey = hasKey('paperclip') || pcServerHasKey

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

  // Dynamic Tauri bundle version. Falls back to the backend's CLI
  // version when running outside the desktop wrapper.
  const [appVersion, setAppVersion] = useState(null)
  useEffect(() => {
    let mounted = true
    if (isTauri()) {
      getAppVersion()
        .then((v) => { if (mounted) setAppVersion(v) })
        .catch(() => {})
    }
    return () => { mounted = false }
  }, [])

  // Tauri auto-updater UI state. The web-ui is also served outside the
  // desktop wrapper (Docker, plain pip install), so we avoid pulling
  // @tauri-apps/plugin-updater as a build-time dep and instead invoke
  // its commands at runtime via the global Tauri IPC bridge. The plugin
  // is registered Rust-side and covered by the `updater:default` and
  // `process:default` capability permissions.
  const [updateChecking, setUpdateChecking] = useState(false)
  const [updateStatus, setUpdateStatus] = useState(null) // { kind, text }
  const handleCheckForUpdates = async () => {
    setUpdateStatus(null)
    if (!isTauri()) {
      setUpdateStatus({ kind: 'info', text: 'Update checks only work inside the desktop app.' })
      return
    }
    setUpdateChecking(true)
    try {
      // plugin:updater|check returns:
      //   null  — no newer version OR signature/platform check failed
      //   { version, current_version, body, date, available?, ... }
      //
      // The plugin returns null silently when the running platform has
      // no matching `platforms.<target>` entry in the manifest (this
      // is how Intel Mac users on an Apple-Silicon-only release see
      // "You're on the latest"). Surface the raw response in the
      // status so the user can distinguish that case from a genuine
      // "up to date" answer.
      const update = await invokeTauri('plugin:updater|check')
      console.info('[updater] check response:', update)
      const noUpdate = !update || update.available === false ||
        (update.version && appVersion && update.version === appVersion)
      if (noUpdate) {
        const hint = appVersion
          ? `You're on ${appVersion}. If a newer version is published but this still says "latest," your Mac may be an Intel build and only arm64 builds ship — grab the right installer from the release page.`
          : "You're on the latest version."
        setUpdateStatus({ kind: 'ok', text: hint })
        return
      }
      setUpdateStatus({ kind: 'info', text: `Downloading ${update.version || 'update'}…` })
      // Tauri 2's `download_and_install` requires the `rid` (resource id)
      // returned by `check` and an `onEvent` Channel for progress events.
      // Pass both — null `onEvent` makes the plugin reject the call,
      // missing `rid` makes it reject with "missing required key rid".
      const { Channel } = await import('@tauri-apps/api/core')
      const channel = new Channel()
      await invokeTauri('plugin:updater|download_and_install', { rid: update.rid, onEvent: channel })
      setUpdateStatus({ kind: 'ok', text: `Update ${update.version || ''} installed — restarting…` })
      setTimeout(() => { invokeTauri('plugin:process|restart').catch(() => {}) }, 600)
    } catch (err) {
      const msg = (err && (err.message || err.toString && err.toString())) || 'Update check failed.'
      setUpdateStatus({ kind: 'error', text: msg })
    } finally {
      setUpdateChecking(false)
    }
  }
  const handleShowReleaseNotes = () => openExternal(`${REPO_URL}/releases/latest`)

  // Diagnostics state
  const [diagBuilding, setDiagBuilding] = useState(false)
  const [diagReport, setDiagReport] = useState(null)
  const [diagCopied, setDiagCopied] = useState(false)
  const handleBuildDiagnostics = async () => {
    setDiagBuilding(true)
    setDiagCopied(false)
    try {
      const report = await collectDiagnostics()
      setDiagReport(report)
    } catch (err) {
      setDiagReport({ error: err?.message || String(err) })
    } finally {
      setDiagBuilding(false)
    }
  }
  const handleCopyDiagnostics = async () => {
    if (!diagReport) return
    try {
      await navigator.clipboard.writeText(diagnosticsToText(diagReport))
      setDiagCopied(true)
      setTimeout(() => setDiagCopied(false), 1500)
    } catch { /* clipboard unavailable */ }
  }
  const handleDownloadDiagnostics = () => {
    if (!diagReport) return
    const text = diagnosticsToText(diagReport)
    const blob = new Blob([text], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `refchecker-diagnostics-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }
  const handleOpenIssueWithDiagnostics = async () => {
    // GitHub rejects ?body= URLs above ~8 KB with a "Whoa there!
    // Your request URL is too long" page. Diagnostic JSON commonly
    // runs 4-20 KB, so we copy the body to the clipboard and open a
    // bare new-issue page. The placeholder body just tells the user
    // to paste — they'll have a single Cmd/Ctrl-V to drop the full
    // report into the issue.
    const body = diagReport
      ? '## What I expected\n\n\n## What happened\n\n\n## Diagnostic report\n\n```json\n' + diagnosticsToText(diagReport) + '\n```\n'
      : '## What I expected\n\n\n## What happened\n\n'
    try {
      await navigator.clipboard.writeText(body)
    } catch { /* clipboard may be unavailable in some contexts */ }
    const shortBody = diagReport
      ? '## What I expected\n\n\n## What happened\n\n\n<!-- Diagnostic report was copied to your clipboard. Paste it here (Cmd/Ctrl-V). -->\n'
      : '## What I expected\n\n\n## What happened\n\n'
    const url = `${ISSUES_URL}/issues/new?body=${encodeURIComponent(shortBody)}`
    openExternal(url)
  }

  // Local DB downloader state — drives the "Build local databases" inline
  // section under the db_path field. Selected DBs run via the existing
  // local_database_updater script through /api/databases/download.
  const [dbBuildOpen, setDbBuildOpen] = useState(false)
  const [dbBuildPick, setDbBuildPick] = useState({ s2: true, dblp: true, openalex: true })
  const [dbBuildMinYear, setDbBuildMinYear] = useState('2020')
  const [dbBuildStatus, setDbBuildStatus] = useState({}) // { s2: {status, log_tail, error}, ... }
  const [dbBuildStarting, setDbBuildStarting] = useState(false)
  const [dbBuildError, setDbBuildError] = useState(null)

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

  // Poll download status while the panel is open AND any task is running.
  useEffect(() => {
    if (!dbBuildOpen) return
    let cancelled = false
    const poll = async () => {
      try {
        const res = await api.getDatabaseDownloadStatus()
        if (cancelled) return
        setDbBuildStatus(res.data.tasks || {})
      } catch {
        // settings panel can stay open in multiuser mode where caller isn't admin
      }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dbBuildOpen])

  const handleDbBuildStart = async () => {
    setDbBuildError(null)
    const databases = Object.entries(dbBuildPick).filter(([, v]) => v).map(([k]) => k)
    if (!databases.length) {
      setDbBuildError('Pick at least one database to build.')
      return
    }
    setDbBuildStarting(true)
    try {
      const payload = { databases }
      const minYear = parseInt(dbBuildMinYear, 10)
      if (!Number.isNaN(minYear) && minYear >= 1900 && minYear <= 2100) {
        payload.openalex_min_year = minYear
      }
      if (dbPathLocal && dbPathLocal.trim()) {
        payload.directory = dbPathLocal.trim()
      }
      const res = await api.triggerDatabaseDownload(payload)
      if (res.data?.directory && !dbPathLocal) {
        setDbPathLocal(res.data.directory)
      }
      fetchSettings()
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      setDbBuildError(detail || 'Failed to start')
    } finally {
      setDbBuildStarting(false)
    }
  }

  const handleDbBuildCancel = async (dbName) => {
    try {
      await api.cancelDatabaseDownload(dbName)
    } catch {
      // ignore — UI will reflect the next poll
    }
  }

  // One-click "use default location" — backend resolves the canonical
  // path under the per-user data dir, creates it, and persists the
  // setting in a single round-trip.
  const handleAutoCreate = async (setting) => {
    try {
      const res = await api.autoCreatePath(setting)
      const path = res.data?.path
      if (!path) return
      if (setting === 'cache_dir') {
        setCacheDirLocal(path)
        setCacheDirError(null)
        setCacheDirSuccess('Default cache directory created.')
        updateSetting('cache_dir', path)
      } else if (setting === 'db_path') {
        setDbPathLocal(path)
        setDbPathError(null)
        setDbPathSuccess('Default database directory created.')
      }
      fetchSettings()
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to auto-create'
      if (setting === 'cache_dir') setCacheDirError(msg)
      else setDbPathError(msg)
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

  // Same for Paperclip — server tells us whether a local key is on file.
  // In multi-user mode the endpoint returns browser-only/no server key,
  // while useKeyStore tracks the user's browser-cached key.
  useEffect(() => {
    api.getPaperclipKeyStatus().then(res => {
      setPcServerHasKey(res.data.has_key)
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

  const notifyApiKeyStatusChanged = () => {
    try { window.dispatchEvent(new CustomEvent('refchecker:api-keys-updated')) } catch { /* event dispatch is advisory; ignore failures */ }
  }

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
      notifyApiKeyStatusChanged()
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
      notifyApiKeyStatusChanged()
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

  // Paperclip key handlers — same shape as SS but no separate
  // /validate endpoint (Paperclip has no public validate API).
  const handlePcSave = async () => {
    if (!pcApiKey.trim()) {
      setPcError('API key cannot be empty')
      return
    }
    try {
      setPcIsSaving(true)
      setPcError(null)
      if (multiuser) {
        setKey('paperclip', pcApiKey.trim())
        setPcServerHasKey(false)
      } else {
        await api.setPaperclipKey(pcApiKey.trim())
        deleteKey('paperclip')
        setPcServerHasKey(true)
      }
      setPcIsEditing(false)
      setPcApiKey('')
      notifyApiKeyStatusChanged()
      logger.info('SettingsPanel', 'Paperclip API key saved')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to save Paperclip key', err)
      setPcError(err.response?.data?.detail || 'Failed to save API key')
    } finally {
      setPcIsSaving(false)
    }
  }

  const handlePcDelete = async () => {
    setPcIsSaving(true)
    try {
      if (multiuser) {
        deleteKey('paperclip')
      } else {
        await api.deletePaperclipKey()
        deleteKey('paperclip')
      }
      setPcServerHasKey(false)
      setPcIsEditing(false)
      setPcApiKey('')
      setPcError(null)
      notifyApiKeyStatusChanged()
      logger.info('SettingsPanel', 'Paperclip API key removed')
    } catch (err) {
      logger.error('SettingsPanel', 'Failed to delete Paperclip key', err)
    } finally {
      setPcIsSaving(false)
    }
  }

  const handlePcCancel = () => {
    setPcIsEditing(false)
    setPcApiKey('')
    setPcError(null)
  }

  const renderAIDetectionSection = () => {
    const ms = aiDetection.modelStatus
    const rs = aiDetection.runtimeStatus
    const backend = aiDetection.backend
    const fmtMB = (b) => (b ? `${(b / (1024 * 1024)).toFixed(0)} MB` : '')
    const aiKeyName = aiDetection.service // 'pangram' | 'gptzero'
    const accent = 'var(--color-accent, #3b82f6)'
    return (
      <div className="space-y-4">
        {/* Permanent honesty banner — warning token pair so it flips between
            light/dark, matching AIDetectionPanel's medium-band styling. */}
        <div
          className="rounded-lg p-3 text-sm border"
          style={{ borderColor: 'var(--color-warning)', backgroundColor: 'var(--color-warning-bg)', color: 'var(--color-text-secondary)' }}
        >
          <strong style={{ color: 'var(--color-text-primary)' }}>Read before enabling.</strong> AI-text
          detection is unreliable on academic, technical, and non-native-English writing, and on
          human text polished with AI. Results are an advisory self-check — <strong>never</strong> proof
          of misconduct, and never a basis for an accusation, grade, or decision.
        </div>

        {/* Enable toggle */}
        <label className="flex items-center justify-between gap-3 py-2 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <span>
            <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Detect AI-generated text</span>
            <span className="block text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              When on, each checked article also gets an AI-likelihood band. Off by default.
            </span>
          </span>
          <input
            type="checkbox"
            checked={aiDetection.enabled}
            onChange={(e) => aiDetection.setEnabled(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: 'var(--color-accent)' }}
          />
        </label>

        {/* Run mode — what a check actually runs. Off = references only;
            on splits into "both" or "AI text only" (skips reference checking). */}
        {aiDetection.enabled && (
          <div className="py-1">
            <div className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>Run mode</div>
            <div className="text-xs mb-1.5" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
              Turn off “Detect AI-generated text” above for reference checking only.
            </div>
            {[
              ['both', 'Reference check + AI detection', 'Verify the bibliography AND analyze the body text for AI-generated content.'],
              ['ai_only', 'AI detection only', 'Skip reference extraction & verification — just analyze the body text. Faster when you only want the AI signal.'],
            ].map(([id, label, desc]) => (
              <label key={id} className="flex items-start gap-2 py-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="detection-run-mode"
                  checked={(aiDetection.detectionMode || 'both') === id}
                  onChange={() => aiDetection.setDetectionMode(id)}
                  style={{ marginTop: 3, accentColor: 'var(--color-accent)' }}
                />
                <span>
                  <span style={{ color: 'var(--color-text-primary)' }}>{label}</span>
                  <span className="block text-xs" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>{desc}</span>
                </span>
              </label>
            ))}
          </div>
        )}

        {/* Engine selector */}
        <div className="py-1">
          <div className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>Detection engine</div>
          {[
            ['local', 'Local model (offline, calibrated)', 'desklib DeBERTa — runs on your machine after a one-time download. Recommended for reproducibility.'],
            ['llm-judge', 'LLM judge (uses hallucination-check LLM)', 'Reuses the same provider, API key, and model selected for hallucination checks. No download, but scores are uncalibrated.'],
            ['api', 'External API (Pangram / GPTZero)', 'Sends manuscript text to a third-party service. Requires a key and explicit consent.'],
          ].map(([id, label, desc]) => (
            <label key={id} className="flex items-start gap-2 py-1.5 cursor-pointer">
              <input
                type="radio"
                name="ai-detection-backend"
                checked={backend === id}
                onChange={() => aiDetection.setBackend(id)}
                style={{ marginTop: 3, accentColor: 'var(--color-accent)' }}
              />
              <span>
                <span style={{ color: 'var(--color-text-primary)' }}>{label}</span>
                <span className="block text-xs" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>{desc}</span>
              </span>
            </label>
          ))}
        </div>

        {/* Local model management */}
        {backend === 'local' && (
          <div className="rounded-lg p-3 border" style={{ borderColor: 'var(--color-border)' }}>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Local detection model</div>
                <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  {ms == null && 'Checking status…'}
                  {ms && ms.installed && `Installed${ms.size_bytes ? ` · ${fmtMB(ms.size_bytes)}` : ''} · ${ms.repo}`}
                  {ms && !ms.installed && ms.deps_available && 'Not downloaded yet.'}
                  {ms && !ms.installed && !ms.deps_available &&
                    'Inference runtime not installed — install it below, or use the LLM-judge / API engine.'}
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                  Model:{' '}
                  <a
                    href={`https://huggingface.co/${ms?.repo || 'desklib/ai-text-detector-v1.01'}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(`https://huggingface.co/${ms?.repo || 'desklib/ai-text-detector-v1.01'}`) } }}
                    style={{ color: 'var(--color-link, #3b82f6)', textDecoration: 'underline' }}
                  >
                    {ms?.repo || 'desklib/ai-text-detector-v1.01'}
                  </a>
                  {' '}— DeBERTa-v3 detector by Desklib (MIT), via Hugging Face.
                </div>
                {aiDetection.modelError && (
                  <div className="text-xs mt-1 rounded p-2 whitespace-pre-wrap" style={{ color: 'var(--color-error, #ef4444)', backgroundColor: 'var(--color-error-bg, rgba(239,68,68,0.1))' }}>{aiDetection.modelError}</div>
                )}
              </div>
              <div className="flex gap-2">
                {ms && !ms.installed && (
                  <button
                    type="button"
                    disabled={aiDetection.modelBusy || (ms && !ms.deps_available)}
                    onClick={() => aiDetection.downloadModel()}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium"
                    style={{ backgroundColor: accent, color: 'white', opacity: (aiDetection.modelBusy || !ms.deps_available) ? 0.5 : 1, cursor: (aiDetection.modelBusy || !ms.deps_available) ? 'not-allowed' : 'pointer' }}
                  >
                    {aiDetection.modelBusy ? 'Downloading…' : 'Download model'}
                  </button>
                )}
                {ms && ms.installed && (
                  <button
                    type="button"
                    disabled={aiDetection.modelBusy}
                    onClick={() => aiDetection.deleteModel()}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium border"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)', opacity: aiDetection.modelBusy ? 0.5 : 1, cursor: aiDetection.modelBusy ? 'not-allowed' : 'pointer' }}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
            {ms && ms.installed && modelUpdate?.update_available && !aiDetection.modelBusy && (
              <div className="mt-2 flex items-center justify-between flex-wrap gap-2 rounded-lg p-2"
                style={{ backgroundColor: 'var(--color-accent-bg, rgba(59,130,246,0.1))', border: '1px solid var(--color-accent, #3b82f6)' }}>
                <div className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  A newer version of the detection model is available.
                </div>
                <button
                  type="button"
                  disabled={aiDetection.modelBusy}
                  onClick={async () => {
                    try {
                      await aiDetection.deleteModel()
                      await aiDetection.downloadModel()
                      setModelUpdate(null)
                    } catch { /* surfaced via aiDetection.modelError */ }
                  }}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium"
                  style={{ backgroundColor: accent, color: 'white' }}
                >
                  Update model
                </button>
              </div>
            )}
            {(aiDetection.modelBusy || (ms && ms.state === 'downloading')) && (
              <div className="mt-2">
                <div style={{ height: 6, borderRadius: 4, background: 'var(--color-border)', overflow: 'hidden' }}>
                  <div className="animate-pulse" style={{ height: '100%', width: '45%', background: accent, borderRadius: 4 }} />
                </div>
                <div className="text-[11px] mt-1 font-mono truncate" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                  {(ms && ms.message) || 'Downloading…'}
                </div>
              </div>
            )}
            {ms && !ms.deps_available && (
              <div className="mt-3 pt-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Inference runtime</div>
                <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                  The local model needs <strong>torch + transformers</strong> (it ships safetensors). Install it
                  here — a one-time download — or use the LLM-judge / API engine, which need no runtime.
                </div>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <button
                    type="button"
                    disabled={aiDetection.runtimeBusy}
                    onClick={() => aiDetection.installRuntime('torch')}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium"
                    style={{ backgroundColor: accent, color: 'white', opacity: aiDetection.runtimeBusy ? 0.5 : 1, cursor: aiDetection.runtimeBusy ? 'not-allowed' : 'pointer' }}
                  >
                    {aiDetection.runtimeBusy ? 'Installing runtime…' : 'Install runtime'}
                  </button>
                  <span className="text-xs" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                    {aiDetection.runtimeBusy
                      ? (rs && rs.message) || 'Downloading torch + transformers…'
                      : 'Large one-time download (torch).'}
                  </span>
                </div>
                {(aiDetection.runtimeBusy || (rs && rs.state === 'installing')) && (
                  <div className="mt-2">
                    <div style={{ height: 6, borderRadius: 4, background: 'var(--color-border)', overflow: 'hidden' }}>
                      <div className="animate-pulse" style={{ height: '100%', width: '45%', background: accent, borderRadius: 4 }} />
                    </div>
                    {rs && rs.log && rs.log.length > 0 && (
                      <div className="text-[11px] mt-1 font-mono truncate" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                        {rs.log[rs.log.length - 1]}
                      </div>
                    )}
                  </div>
                )}
                {aiDetection.runtimeError && (
                  <div className="text-xs mt-2 rounded p-2 whitespace-pre-wrap" style={{ color: 'var(--color-error, #ef4444)', backgroundColor: 'var(--color-error-bg, rgba(239,68,68,0.1))' }}>{aiDetection.runtimeError}</div>
                )}
                {rs && rs.is_frozen && (
                  <div className="text-xs mt-1" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                    Installs into the app’s data folder. If it can’t install here, run{' '}
                    <code>pip install torch transformers</code> in your environment instead.
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* R61 — Multi-detector manager. Lists the DETECTOR_REGISTRY roster with
            real size/license/tier; install/remove per detector with progress;
            Tier-2 (heavy) rows show the explicit resource warning and are
            disabled when unavailable. The single-model card above is preserved
            for existing users; this is additive. */}
        {backend === 'local' && aiDetection.detectors.length > 0 && (
          <div className="rounded-lg p-3 border space-y-3" style={{ borderColor: 'var(--color-border)' }}>
            <div>
              <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Detectors</div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                Install one or more open-source detectors and run them side by side. Each shows its
                own verdict — there is no blended “ensemble” score. Heavy (Tier-2) detectors download
                multi-GB models and need extra RAM.
              </div>
              {/* R61 — run-selection helper. Only INSTALLED detectors can be put
                  into the run set (the store guards this); an empty selection
                  falls back to the single default detector for existing users. */}
              <div className="text-xs mt-1.5" style={{ color: 'var(--color-text-secondary)' }}>
                {aiDetection.selectedDetectors.length > 0
                  ? `Next check will run: ${aiDetection.selectedDetectors.join(', ')}`
                  : 'Tick “Run” on the installed detectors you want the next check to use. With none ticked, the default detector runs.'}
              </div>
            </div>
            <ul className="space-y-2">
              {aiDetection.detectors.map((d) => {
                const busy = !!aiDetection.detectorBusy[d.key]
                const err = aiDetection.detectorError[d.key]
                const heavy = d.tier === 2 || d.heavy
                // A heavy detector with no runtime/host support is disabled.
                const unavailable = d.available === false
                const sizeLabel = d.size_bytes ? fmtMB(d.size_bytes) : (d.size || null)
                return (
                  <li key={d.key} className="rounded-lg p-2.5 border"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)' }}>
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {d.label || d.key}
                          </span>
                          {heavy && (
                            <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded"
                              style={{ color: 'var(--color-warning)', border: '1px solid var(--color-warning)' }}>
                              Tier 2 · heavy
                            </span>
                          )}
                          {d.installed && (
                            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                              style={{ color: 'var(--color-success)', border: '1px solid var(--color-success)' }}>
                              Installed
                            </span>
                          )}
                        </div>
                        <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                          {[d.arch, sizeLabel, d.license].filter(Boolean).join(' · ')}
                        </div>
                        {d.repo && (
                          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>
                            <a
                              href={`https://huggingface.co/${d.repo}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => { if (isTauri()) { e.preventDefault(); openExternal(`https://huggingface.co/${d.repo}`) } }}
                              style={{ color: 'var(--color-link, #3b82f6)', textDecoration: 'underline' }}
                            >
                              {d.repo}
                            </a>
                          </div>
                        )}
                        {d.raid_note && (
                          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted, #94a3b8)' }}>{d.raid_note}</div>
                        )}
                        {heavy && (
                          <div className="text-xs mt-1 rounded p-1.5"
                            style={{ color: 'var(--color-text-secondary)', backgroundColor: 'var(--color-warning-bg)', border: '1px solid var(--color-warning)' }}>
                            ⚠ Heavy detector — {sizeLabel ? `${sizeLabel} download, ` : ''}large RAM footprint. Opt-in only.
                          </div>
                        )}
                        {err && (
                          <div className="text-xs mt-1 rounded p-1.5 whitespace-pre-wrap"
                            style={{ color: 'var(--color-error, #ef4444)', backgroundColor: 'var(--color-error-bg, rgba(239,68,68,0.1))' }}>{err}</div>
                        )}
                      </div>
                      <div className="flex-shrink-0 flex items-center gap-2">
                        {/* R61 — per-detector "Run" toggle (installed only). Adds
                            the detector to the multi-run set threaded into the
                            next check request as ai_detection_detectors. */}
                        {d.installed && (
                          <label className="flex items-center gap-1.5 text-xs cursor-pointer"
                            style={{ color: 'var(--color-text-secondary)' }}
                            title="Run this detector on the next check (side-by-side with the others ticked)">
                            <input
                              type="checkbox"
                              data-testid={`run-check-${d.key}`}
                              aria-label={`Run ${d.label || d.key} on the next check`}
                              checked={aiDetection.selectedDetectors.includes(d.key)}
                              onChange={() => aiDetection.toggleSelectedDetector(d.key)}
                              style={{ width: 14, height: 14, accentColor: accent }}
                            />
                            Run
                          </label>
                        )}
                        {d.installed ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => aiDetection.removeDetectorByKey(d.key)}
                            className="px-3 py-1.5 rounded-lg text-sm font-medium border"
                            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)', opacity: busy ? 0.5 : 1, cursor: busy ? 'not-allowed' : 'pointer' }}
                          >
                            {busy ? 'Removing…' : 'Remove'}
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={busy || unavailable}
                            title={unavailable ? 'This detector is not available on your system.' : undefined}
                            onClick={() => aiDetection.installDetectorByKey(d.key)}
                            className="px-3 py-1.5 rounded-lg text-sm font-medium"
                            style={{ backgroundColor: accent, color: 'white', opacity: (busy || unavailable) ? 0.5 : 1, cursor: (busy || unavailable) ? 'not-allowed' : 'pointer' }}
                          >
                            {busy ? 'Installing…' : (unavailable ? 'Unavailable' : 'Install')}
                          </button>
                        )}
                      </div>
                    </div>
                    {busy && (
                      <div className="mt-2" style={{ height: 6, borderRadius: 4, background: 'var(--color-border)', overflow: 'hidden' }}>
                        <div className="animate-pulse" style={{ height: '100%', width: '45%', background: accent, borderRadius: 4 }} />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {/* LLM-judge note */}
        {backend === 'llm-judge' && (
          <div className="text-sm rounded-lg p-3 border" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}>
            Uses the same provider, API key, and model selected for hallucination checks under{' '}
            <strong>LLM</strong> / <strong>API Keys</strong>. No extra setup needed.
          </div>
        )}

        {/* External API config */}
        {backend === 'api' && (
          <div className="rounded-lg p-3 border space-y-3" style={{ borderColor: 'var(--color-border)' }}>
            <div>
              <div className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>Service</div>
              <select
                value={aiDetection.service}
                onChange={(e) => aiDetection.setService(e.target.value)}
                className="px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)' }}
              >
                <option value="pangram">Pangram</option>
                <option value="gptzero">GPTZero</option>
              </select>
            </div>
            <div>
              <div className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>API key</div>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={aiDetKey}
                  placeholder={hasKey(aiKeyName) ? '•••••••• (saved)' : `${aiKeyName} API key`}
                  onChange={(e) => setAiDetKey(e.target.value)}
                  className="flex-1 px-2 py-1.5 rounded border text-sm"
                  style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-primary)' }}
                />
                <button
                  type="button"
                  disabled={!aiDetKey.trim()}
                  onClick={() => { if (aiDetKey.trim()) { setKey(aiKeyName, aiDetKey.trim()); setAiDetKey('') } }}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium"
                  style={{ backgroundColor: accent, color: 'white', opacity: aiDetKey.trim() ? 1 : 0.5, cursor: aiDetKey.trim() ? 'pointer' : 'not-allowed' }}
                >
                  Save
                </button>
                {hasKey(aiKeyName) && (
                  <button
                    type="button"
                    onClick={() => deleteKey(aiKeyName)}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium border"
                    style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
            <label className="flex items-start gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <input
                type="checkbox"
                checked={aiDetection.consent}
                onChange={(e) => aiDetection.setConsent(e.target.checked)}
                style={{ marginTop: 3, accentColor: 'var(--color-accent)' }}
              />
              <span>
                I understand the manuscript text (which may be unpublished) will be sent to{' '}
                <strong>{aiDetection.service}</strong>, a third-party service, for analysis.
              </span>
            </label>
          </div>
        )}

        {/* Debugger: runtime install log + recent detection-run events. */}
        <div className="pt-2 mt-1 border-t" style={{ borderColor: 'var(--color-border)' }}>
          <button
            type="button"
            onClick={() => { const n = !aiDebugOpen; setAiDebugOpen(n); if (n) aiDetection.fetchDiagnostics() }}
            className="flex items-center gap-1 text-xs font-medium"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <span style={{ display: 'inline-block', width: 10 }}>{aiDebugOpen ? '▾' : '▸'}</span>
            Diagnostics &amp; logs
          </button>
          {aiDebugOpen && (
            <div className="mt-2 space-y-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  Runtime: {rs ? `${rs.deps_available ? 'ready' : (rs.state || 'idle')}${rs.installed_variant ? ` · ${rs.installed_variant}` : ''}${rs.is_frozen ? ' · desktop' : ''}` : '…'}
                  {rs && rs.target ? ` · ${rs.target}` : ''}
                </span>
                <button type="button" onClick={() => aiDetection.fetchDiagnostics()} className="text-xs underline" style={{ color: accent }}>
                  Refresh
                </button>
              </div>
              <div>
                <div className="text-[11px] mb-1" style={{ color: 'var(--color-text-muted)' }}>Install log</div>
                <pre
                  className="text-[11px] rounded p-2 overflow-auto m-0"
                  style={{ maxHeight: 170, backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                >
                  {rs && rs.log && rs.log.length ? rs.log.join('\n') : 'No install log yet — click “Install runtime”.'}
                </pre>
              </div>
              {(() => {
                const mlog = (ms && ms.log && ms.log.length)
                  ? ms.log
                  : ((aiDetection.diagnostics && aiDetection.diagnostics.model && aiDetection.diagnostics.model.log) || [])
                return (
                  <div>
                    <div className="text-[11px] mb-1" style={{ color: 'var(--color-text-muted)' }}>Model download log</div>
                    <pre
                      className="text-[11px] rounded p-2 overflow-auto m-0"
                      style={{ maxHeight: 140, backgroundColor: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                    >
                      {mlog.length ? mlog.join('\n') : 'No model download log yet — click “Download model”.'}
                    </pre>
                  </div>
                )
              })()}
              <div>
                <div className="text-[11px] mb-1" style={{ color: 'var(--color-text-muted)' }}>Recent detection runs</div>
                {(() => {
                  const evs = (aiDetection.diagnostics && aiDetection.diagnostics.events) || []
                  if (!evs.length) {
                    return <div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>No detection runs recorded yet (run a check with AI detection on).</div>
                  }
                  return (
                    <div className="text-[11px] font-mono space-y-0.5 rounded p-2 overflow-auto" style={{ maxHeight: 170, backgroundColor: 'var(--color-bg-secondary)' }}>
                      {evs.map((e, i) => (
                        <div key={i} style={{ color: 'var(--color-text-secondary)' }}>
                          {e.ts} · {e.backend} · <strong>{e.outcome}</strong>
                          {e.score != null ? ` (${Number(e.score).toFixed(2)})` : ''}
                          {e.reason ? ` · ${e.reason}` : ''}
                          {e.word_count != null ? ` · ${e.word_count}w` : ''}
                          {e.duration_ms != null ? ` · ${e.duration_ms}ms` : ''}
                          {e.error ? ` · ${e.error}` : ''}
                        </div>
                      ))}
                    </div>
                  )
                })()}
              </div>
            </div>
          )}
        </div>

        {/* Attribution for the open-source detectors / services used. */}
        <div className="pt-2 mt-1 border-t text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
          <div className="mb-1">Detection sources & credits:</div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {[
              ['desklib/ai-text-detector (local model, MIT)', 'https://huggingface.co/desklib/ai-text-detector-v1.01'],
              ['harshaneel/humanize (LLM-judge rubric, MIT)', 'https://github.com/harshaneel/humanize'],
              ['distil-labs/distil-ai-slop-detector', 'https://github.com/distil-labs/distil-ai-slop-detector'],
              ['Pangram', 'https://www.pangram.com'],
              ['GPTZero', 'https://gptzero.me'],
            ].map(([label, url]) => (
              <button
                key={url}
                type="button"
                onClick={() => openExternal(url)}
                className="underline"
                style={{ color: 'var(--color-accent, #3b82f6)' }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Accounts & Teams — the single, always-reachable entry point for sign-in
  // and team management, even in the single-user desktop build. Multi-user mode
  // (OAuth login + Teams) is enabled server-side via REFCHECKER_MULTIUSER=true
  // plus OAuth client credentials; the frontend cannot flip that flag, so when
  // it is off we explain exactly how to turn it on instead of faking a session.
  const accent = 'var(--color-accent, #3b82f6)'

  const PROVIDER_META = {
    google: { label: 'Continue with Google', login: loginWithGoogle },
    github: { label: 'Continue with GitHub', login: loginWithGithub },
    microsoft: { label: 'Continue with Microsoft', login: loginWithMicrosoft },
  }

  const renderAccountsSection = () => {
    // State A — auth enabled AND signed in: show the account + a path to Teams.
    if (authRequired && authUser) {
      const initials = (authUser.name || authUser.email || '?')
        .split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase()
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-3 py-2">
            {authUser.avatar_url ? (
              <img src={authUser.avatar_url} alt={authUser.name || 'User avatar'} className="w-12 h-12 rounded-full object-cover" />
            ) : (
              <div className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-semibold text-white" style={{ backgroundColor: accent }}>
                {initials}
              </div>
            )}
            <div className="min-w-0">
              {authUser.name && <div className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>{authUser.name}</div>}
              {authUser.email && <div className="text-sm truncate" style={{ color: 'var(--color-text-secondary)' }}>{authUser.email}</div>}
              {authUser.provider && <div className="text-xs mt-0.5 capitalize" style={{ color: 'var(--color-text-muted, #9ca3af)' }}>Signed in via {authUser.provider}</div>}
            </div>
          </div>

          <div className="py-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Teams</div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              Create a team and add or remove members from the <strong>Teams</strong> menu in the header
              (the people icon, top-right). Members share checks and a team activity log.
            </div>
          </div>

          <div className="pt-1">
            <button
              type="button"
              onClick={() => { authLogout(); closeSettings() }}
              className="px-3 py-1.5 rounded-lg text-sm font-medium border"
              style={{ borderColor: 'var(--color-error, #ef4444)', color: 'var(--color-error, #ef4444)' }}
            >
              Sign out
            </button>
          </div>
        </div>
      )
    }

    // State B — auth enabled but signed out: surface the OAuth sign-in buttons
    // right here so the user can reach login without hunting for it.
    if (authRequired && authProviders.length > 0) {
      return (
        <div className="space-y-4">
          <div>
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Sign in</div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              Accounts are enabled on this server. Sign in to sync your checks and manage teams.
            </div>
          </div>
          <div className="flex flex-col gap-2 max-w-sm">
            {authProviders.map((p) => {
              const meta = PROVIDER_META[p]
              if (!meta) return null
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => meta.login()}
                  className="w-full px-4 py-2.5 rounded-lg text-sm font-medium border"
                  style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  {meta.label}
                </button>
              )
            })}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-muted, #9ca3af)' }}>
            After signing in, the <strong>Teams</strong> menu appears in the header for creating teams and managing members.
          </div>
        </div>
      )
    }

    // State C — single-user desktop default: accounts/teams are off. Be honest
    // about why, and explain exactly how to enable them (no fake logged-in state).
    return (
      <div className="space-y-4">
        <div
          className="rounded-lg p-3 text-sm border"
          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-secondary)' }}
        >
          <strong style={{ color: 'var(--color-text-primary)' }}>You're in single-user mode.</strong>{' '}
          This desktop build runs locally with no account — all your checks stay on this machine.
          Sign-in (Google / GitHub / Microsoft) and Teams are <strong>opt-in</strong> and require enabling
          multi-user mode on the server, so they're hidden by default.
        </div>

        <div>
          <div className="font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>Enable accounts &amp; Teams</div>
          {/* Actionable in-app enablement: enter OAuth creds + flip the switch,
              the backend persists it and the app relaunches in multi-user mode. */}
          <EnableAccountsForm accent={accent} repoUrl={REPO_URL} />
        </div>
      </div>
    )
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
    { id: 'AI Detection', label: 'AI Detection', icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.456-2.456L14.25 6l1.035-.259a3.375 3.375 0 002.456-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
      </svg>
    )},
    { id: 'Accounts', label: 'Accounts & Teams', icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    )},
  ]

  const renderGeneralSection = () => (
    <div className="space-y-1">
      {/* App updates — only meaningful inside the Tauri desktop app */}
      {isTauri() && (
        <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
            <div>
              <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>App updates</div>
              <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
                {appVersion ? `Currently on v${appVersion}` : 'Check the manifest for a newer signed build.'}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCheckForUpdates}
                disabled={updateChecking}
                className="px-3 py-1.5 rounded-lg text-sm font-medium"
                style={{
                  backgroundColor: 'var(--color-accent, #3b82f6)',
                  color: 'white',
                  opacity: updateChecking ? 0.6 : 1,
                }}
                type="button"
              >
                {updateChecking ? 'Checking…' : 'Check for updates'}
              </button>
              <button
                onClick={handleShowReleaseNotes}
                className="px-3 py-1.5 rounded-lg text-sm font-medium border"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                type="button"
              >
                Show changes
              </button>
            </div>
          </div>
          {updateStatus && (
            <div
              className="text-xs"
              style={{
                color: updateStatus.kind === 'ok'
                  ? 'var(--color-success, #22c55e)'
                  : updateStatus.kind === 'error'
                    ? 'var(--color-error, #ef4444)'
                    : 'var(--color-text-secondary)',
              }}
            >
              {updateStatus.text}
            </div>
          )}
        </div>
      )}

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

      {/* Reference Extraction Mode */}
      {settings.extraction_mode && (
        <div className="flex items-center justify-between py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex-1 mr-3">
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {settings.extraction_mode.label || 'Reference Extraction'}
            </div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              {settings.extraction_mode.description}
            </div>
          </div>
          <div className="relative">
            <select
              value={settings.extraction_mode.value || 'cascade'}
              onChange={(e) => handleSettingChange('extraction_mode', e.target.value)}
              className="appearance-none px-4 py-2 pr-8 rounded-lg border text-sm cursor-pointer"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
                colorScheme: 'light dark',
                minWidth: '180px',
              }}
            >
              <option value="cascade" style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}>Cascade (cheap-first)</option>
              <option value="llm-only" style={{ backgroundColor: 'var(--color-bg-primary)', color: 'var(--color-text-primary)' }}>LLM only</option>
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
      )}

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
            <button
              onClick={() => handleAutoCreate('db_path')}
              disabled={dbPathSaving}
              className="px-3 py-2 rounded-lg text-sm font-medium border"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
              title="Create the default database directory under the app data dir and save it as the setting"
              type="button"
            >
              Use default
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

          {/* Build local databases — only useful in the single-user desktop
              flow, so it sits inside the same single-user-gated section. */}
          <div className="mt-3">
            <button
              onClick={() => setDbBuildOpen((v) => !v)}
              className="text-xs underline"
              style={{ color: 'var(--color-accent, #3b82f6)' }}
              type="button"
            >
              {dbBuildOpen ? 'Hide local database builder' : 'Build local databases (Semantic Scholar, DBLP, OpenAlex)'}
            </button>
          </div>

          {dbBuildOpen && (
            <div
              className="mt-3 p-3 rounded-lg border"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}
            >
              <div className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                Runs the bundled <code>local_database_updater</code> against the directory above (or
                a default under the app data dir if blank). First builds can be large (multi-GB) and
                run in the background — close this panel anytime, status persists.
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
                {[
                  ['s2', 'Semantic Scholar'],
                  ['dblp', 'DBLP'],
                  ['openalex', 'OpenAlex'],
                ].map(([key, label]) => {
                  const state = dbBuildStatus[key]
                  return (
                    <label
                      key={key}
                      className="flex items-center gap-2 text-sm"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <input
                        type="checkbox"
                        checked={!!dbBuildPick[key]}
                        onChange={(e) => setDbBuildPick({ ...dbBuildPick, [key]: e.target.checked })}
                      />
                      <span className="flex-1">{label}</span>
                      {state && (
                        <span
                          className="text-xs px-2 py-0.5 rounded"
                          style={{
                            backgroundColor:
                              state.status === 'success' ? 'var(--color-success, #22c55e)' :
                              state.status === 'failed' ? 'var(--color-error, #ef4444)' :
                              state.status === 'cancelled' ? 'var(--color-warning, #f59e0b)' :
                              'var(--color-accent, #3b82f6)',
                            color: 'white',
                          }}
                        >
                          {state.status}
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>

              <div className="flex items-center gap-2 mb-3">
                <label className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                  OpenAlex minimum year
                </label>
                <input
                  type="number"
                  min="1900"
                  max="2100"
                  step="1"
                  value={dbBuildMinYear}
                  onChange={(e) => setDbBuildMinYear(e.target.value)}
                  className="px-2 py-1 rounded border text-sm"
                  style={{
                    width: '90px',
                    backgroundColor: 'var(--color-bg-primary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  (caps OpenAlex partitions to keep the dump manageable)
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleDbBuildStart}
                  disabled={dbBuildStarting}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium"
                  style={{
                    backgroundColor: 'var(--color-accent, #3b82f6)',
                    color: 'white',
                    opacity: dbBuildStarting ? 0.6 : 1,
                  }}
                  type="button"
                >
                  {dbBuildStarting ? 'Starting…' : 'Start build'}
                </button>
                {Object.entries(dbBuildStatus).some(([, s]) => s.status === 'running') && (
                  <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    Building in background. Cancel a job from its tag above —
                    {' '}
                    {Object.entries(dbBuildStatus)
                      .filter(([, s]) => s.status === 'running')
                      .map(([k]) => (
                        <button
                          key={k}
                          onClick={() => handleDbBuildCancel(k)}
                          className="underline ml-1"
                          style={{ color: 'var(--color-accent, #3b82f6)' }}
                          type="button"
                        >
                          cancel {k}
                        </button>
                      ))}
                  </span>
                )}
              </div>

              {dbBuildError && (
                <div className="text-xs mt-2" style={{ color: 'var(--color-error, #ef4444)' }}>
                  {dbBuildError}
                </div>
              )}

              {Object.entries(dbBuildStatus).some(([, s]) => s.log_tail) && (
                <details className="mt-3">
                  <summary
                    className="text-xs cursor-pointer"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    Show last log lines per database
                  </summary>
                  {Object.entries(dbBuildStatus).map(([k, s]) =>
                    s.log_tail ? (
                      <div key={k} className="mt-2">
                        <div className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>{k}</div>
                        <pre
                          className="text-xs p-2 rounded overflow-x-auto"
                          style={{
                            backgroundColor: 'var(--color-bg-secondary)',
                            color: 'var(--color-text-secondary)',
                          }}
                        >{s.log_tail}</pre>
                      </div>
                    ) : null
                  )}
                </details>
              )}
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
            <button
              onClick={() => handleAutoCreate('cache_dir')}
              disabled={cacheDirSaving}
              className="px-3 py-2 rounded-lg text-sm font-medium border"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
              title="Create the default cache directory under the app data dir and save it as the setting"
              type="button"
            >
              Use default
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

      {/* Diagnostics — Settings → General → bottom. Builds a sanitized
          JSON report (env, backend health, settings, recent console)
          that the user can paste into a GitHub issue. */}
      <div className="py-3" style={{ borderColor: 'var(--color-border)' }}>
        <div className="mb-2">
          <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Diagnostics</div>
          <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
            Build a sanitized report of the running environment for bug reports. API keys, secrets, and paths are redacted before display.
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={handleBuildDiagnostics}
            disabled={diagBuilding}
            className="px-3 py-1.5 rounded-lg text-sm font-medium"
            style={{ backgroundColor: 'var(--color-accent, #3b82f6)', color: 'white', opacity: diagBuilding ? 0.6 : 1 }}
            type="button"
          >
            {diagBuilding ? 'Collecting…' : 'Generate report'}
          </button>
          <button
            onClick={handleCopyDiagnostics}
            disabled={!diagReport || diagBuilding}
            className="px-3 py-1.5 rounded-lg text-sm font-medium border"
            style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', opacity: diagReport && !diagBuilding ? 1 : 0.5 }}
            type="button"
          >
            {diagCopied ? '✓ Copied' : 'Copy JSON'}
          </button>
          <button
            onClick={handleDownloadDiagnostics}
            disabled={!diagReport || diagBuilding}
            className="px-3 py-1.5 rounded-lg text-sm font-medium border"
            style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', opacity: diagReport && !diagBuilding ? 1 : 0.5 }}
            type="button"
          >
            Download
          </button>
          <button
            onClick={handleOpenIssueWithDiagnostics}
            disabled={diagBuilding}
            className="px-3 py-1.5 rounded-lg text-sm font-medium border"
            style={{ backgroundColor: 'var(--color-bg-primary)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)', opacity: diagBuilding ? 0.5 : 1 }}
            type="button"
            title="Open a new GitHub issue with the report prefilled"
          >
            Open issue with report
          </button>
        </div>
        {diagReport && (
          <details className="mt-3">
            <summary className="text-xs cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
              Preview report (click to expand)
            </summary>
            <pre
              className="text-[11px] p-2 mt-2 rounded overflow-auto"
              style={{
                backgroundColor: 'var(--color-bg-primary)',
                color: 'var(--color-text-secondary)',
                maxHeight: '300px',
                border: '1px solid var(--color-border)',
              }}
            >{diagnosticsToText(diagReport)}</pre>
          </details>
        )}
      </div>
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
          Chat-with-PDF LLM
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          Used to answer questions about an article, grounded only in its own text. Works with any configured provider.
        </div>
        <div className="mt-3 max-w-sm">
          <LLMSelector mode="chat" />
        </div>
      </div>

      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
          Summarize LLM
        </div>
        <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
          Used to summarize an article, grounded only in its own text. Choose a different model from Chat if you prefer. Defaults to the Chat-with-PDF model until you pick one.
        </div>
        <div className="mt-3 max-w-sm">
          <LLMSelector mode="summarize" />
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

        {/* Paperclip API Key — OPTIONAL biomedical full-text +
          arXiv secondary verification tier. In multi-user mode the
          key stays in the browser cache and is sent per request; in
          single-user mode it is stored locally and restored on restart. */}
      <div className="py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center justify-between mb-1">
          <div>
            <div className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
              Paperclip API Key
            </div>
            <div className="text-sm mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>
              Optional. Activates a secondary biomedical full-text + arXiv lookup tier
              (PMC, bioRxiv, medRxiv, arXiv) on top of OpenAlex / CrossRef / Semantic
              Scholar. Get a key at{' '}
              <a
                href="https://paperclip.gxl.ai/keys"
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: 'var(--color-link, #3b82f6)' }}
              >paperclip.gxl.ai/keys</a>.
              {' '}The next check picks it up automatically.
              {multiuser && ' Stored in this browser only.'}
            </div>
          </div>
          {!pcIsEditing && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPcIsEditing(true)}
                className="text-xs px-2 py-1 rounded cursor-pointer"
                style={{ color: 'var(--color-accent)' }}
              >
                {pcHasKey ? 'Edit' : 'Set'}
              </button>
              {pcHasKey && (
                <button
                  onClick={handlePcDelete}
                  disabled={pcIsSaving}
                  className="text-xs px-2 py-1 rounded cursor-pointer"
                  style={{ color: 'var(--color-error)' }}
                >
                  Remove
                </button>
              )}
            </div>
          )}
        </div>

        {pcIsEditing && (
          <div className="mt-2 space-y-2">
            <div className="flex gap-2">
              <input
                type="password"
                value={pcApiKey}
                onChange={(e) => setPcApiKey(e.target.value)}
                placeholder="Enter Paperclip API key…"
                className="flex-1 px-2 py-1.5 text-sm rounded border"
                style={{
                  backgroundColor: 'var(--color-bg-primary)',
                  borderColor: pcError ? 'var(--color-error)' : 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                disabled={pcIsSaving}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && pcApiKey.trim()) handlePcSave()
                  if (e.key === 'Escape') handlePcCancel()
                }}
              />
              <button
                onClick={handlePcSave}
                disabled={pcIsSaving || !pcApiKey.trim()}
                className="px-3 py-1.5 text-xs rounded cursor-pointer"
                style={{
                  backgroundColor: 'var(--color-accent)',
                  color: 'white',
                  opacity: pcIsSaving || !pcApiKey.trim() ? 0.5 : 1,
                }}
              >
                {pcIsSaving ? '…' : 'Save'}
              </button>
              <button
                onClick={handlePcCancel}
                disabled={pcIsSaving}
                className="px-3 py-1.5 text-xs rounded border cursor-pointer"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
            </div>
            {pcError && (
              <div className="text-xs" style={{ color: 'var(--color-error)' }}>
                {pcError}
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
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors cursor-pointer text-left"
                style={{
                  backgroundColor: activeSection === item.id ? 'var(--color-bg-tertiary)' : 'transparent',
                  color: activeSection === item.id ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                }}
              >
                {/* Icon never shrinks; the label takes the rest and stays
                    LEFT-aligned even when it wraps to two lines (e.g. "Accounts
                    & Teams") instead of reading centered. */}
                <span className="flex-none flex items-center">{item.icon}</span>
                <span className="flex-1 text-left leading-snug">{item.label}</span>
              </button>
            ))}
          </nav>

          <div className="px-4 mt-6 text-xs leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
            {appVersion && (
              <div>
                Desktop <span style={{ color: 'var(--color-text-secondary)' }}>v{appVersion}</span>
              </div>
            )}
            <div>
              {appVersion ? 'Engine' : 'Version'} {version || '—'}
            </div>
          </div>
        </div>

        {/* Right Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-6 py-4 border-b text-left" style={{ borderColor: 'var(--color-border)' }}>
            {/* Use the nav LABEL (e.g. "Accounts & Teams") not the section id
                ("Accounts"), so the header matches the sidebar entry. */}
            <h2 className="text-lg font-semibold text-left" style={{ color: 'var(--color-text-primary)' }}>
              {navItems.find((n) => n.id === activeSection)?.label || activeSection}
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
                {activeSection === 'AI Detection' && renderAIDetectionSection()}
                {activeSection === 'Accounts' && renderAccountsSection()}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
