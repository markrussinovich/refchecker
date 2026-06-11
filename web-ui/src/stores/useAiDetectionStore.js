import { create } from 'zustand'
import { logger } from '../utils/logger'
import {
  getAIDetectionModelStatus,
  downloadAIDetectionModel,
  deleteAIDetectionModel,
  getAIDetectionRuntimeStatus,
  installAIDetectionRuntime,
  getAIDetectionDiagnostics,
  getDetectors,
  installDetector,
  removeDetector,
} from '../utils/api'

// AI-generated-text detection is an OPT-IN, client-side preference (it is not
// an admin-gated server setting, so non-admin desktop users can toggle it).
// Persisted in localStorage; threaded into each check request by InputSection.
const STORAGE_KEY = 'refchecker.aiDetection.v1'

const DEFAULTS = {
  enabled: false,
  backend: 'local',     // 'local' | 'llm-judge' | 'api'
  service: 'pangram',   // for backend === 'api': 'pangram' | 'gptzero'
  consent: false,       // explicit consent required for the API backend
  // When AI detection is enabled, run it alongside reference checking ('both')
  // or on its own, skipping reference verification ('ai_only'). With AI
  // detection disabled the run is reference-checking-only regardless.
  detectionMode: 'both', // 'both' | 'ai_only'
  // R61 — which installed detectors a check should run with (for the local
  // backend's multi-detector mode). Persisted so the user's chosen roster
  // survives reloads; threaded into the check request like detectionMode. An
  // empty list means "fall back to the default single detector" (backward
  // compatible — existing desklib users keep running desklib unchanged).
  selectedDetectors: [], // e.g. ['desklib', 'superannotate']
}

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch (e) {
    logger.warn('AiDetectionStore', 'Failed to load preferences', e)
  }
  return { ...DEFAULTS }
}

function persist(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      enabled: state.enabled,
      backend: state.backend,
      service: state.service,
      consent: state.consent,
      detectionMode: state.detectionMode,
      selectedDetectors: Array.isArray(state.selectedDetectors) ? state.selectedDetectors : [],
    }))
  } catch (e) {
    logger.warn('AiDetectionStore', 'Failed to persist preferences', e)
  }
}

// R61 — normalize a detection payload into a { detectorKey: result } map.
// The §14-item-2 multi-detector response carries per-detector results as either
// a `detectors` array (each row tagged `key`/`detector`/`detector_key`) or a
// `results_by_detector` object. A legacy single-detector payload has neither —
// we key it by its own model id (model_version/backend_used) so the comparison
// view and single-detector view share one code path. Returns {} for nullish.
export function normalizeResultsByDetector(detection) {
  if (!detection || typeof detection !== 'object') return {}
  const out = {}
  const tagKey = (row, fallback) =>
    row?.detector_key || row?.key || row?.detector || row?.name || fallback
  if (Array.isArray(detection.detectors)) {
    detection.detectors.forEach((row, i) => {
      const key = tagKey(row, `detector_${i}`)
      out[key] = row
    })
    return out
  }
  if (detection.results_by_detector && typeof detection.results_by_detector === 'object') {
    Object.entries(detection.results_by_detector).forEach(([key, row]) => { out[key] = row })
    return out
  }
  // Legacy single-detector payload — key it by its own model id so single and
  // multi paths converge. Strip the comparison-only fields if any.
  const selfKey = detection.detector_key || detection.model_version || detection.backend_used || 'detector'
  out[selfKey] = detection
  return out
}

export const useAiDetectionStore = create((set, get) => ({
  ...load(),

  // Local-model lifecycle state
  modelStatus: null,     // { state, installed, deps_available, size_bytes, ... }
  modelBusy: false,
  modelError: null,

  // Optional inference-runtime (torch/onnx) lifecycle state
  runtimeStatus: null,   // { deps_available, installed_variant, is_frozen, log, ... }
  runtimeBusy: false,
  runtimeError: null,

  // Debugger payload: { runtime: {...}, events: [...] }
  diagnostics: null,

  // R61 — multi-detector registry lifecycle. `detectors` is the §14 roster:
  // [{ key, label, repo, arch, tier, heavy, size_bytes, license, raid_note,
  //    installed, available }]. `detectorBusy` maps key → true while that
  // detector is installing/removing (per-key so one install doesn't disable
  // the whole list). `detectorError` maps key → message.
  detectors: [],          // registry rows (empty until fetchDetectors runs)
  detectorBusy: {},       // { [key]: bool }
  detectorError: {},      // { [key]: string }

  // R61 — multi-detector RESULTS for the comparison view. `resultsByDetector`
  // maps detector key → that detector's own { score, band, spans, ... } result.
  // HONESTY: only detectors that actually ran appear here — there is NO
  // synthetic ensemble entry. `exportSelection` is the set of detector keys the
  // user has checkbox-selected for "Export selected".
  resultsByDetector: {},  // { [key]: { score, band, spans, ... } }
  exportSelection: [],    // detector keys checked for export

  setEnabled: (enabled) => { set({ enabled }); persist(get()) },
  setBackend: (backend) => { set({ backend }); persist(get()) },
  setService: (service) => { set({ service }); persist(get()) },
  setConsent: (consent) => { set({ consent }); persist(get()) },
  setDetectionMode: (detectionMode) => { set({ detectionMode }); persist(get()) },

  // ---- R61: selected-detectors-to-run (multi-select of INSTALLED detectors) ----
  // Only installed detectors may be selected — an uninstalled detector can
  // never run, so it can never be put into the run set (the manager guards this
  // too). setSelectedDetectors filters against the known registry when it has
  // one; toggleSelectedDetector is the per-row checkbox handler.
  setSelectedDetectors: (keys) => {
    const list = Array.isArray(keys) ? keys : []
    const installed = new Set(get().detectors.filter((d) => d.installed).map((d) => d.key))
    // If we have a registry, keep only installed keys; otherwise trust the caller.
    const next = installed.size > 0 ? list.filter((k) => installed.has(k)) : list
    set({ selectedDetectors: Array.from(new Set(next)) })
    persist(get())
  },
  toggleSelectedDetector: (key) => {
    const cur = get().selectedDetectors || []
    const has = cur.includes(key)
    if (!has) {
      // Refuse to select a detector that isn't installed (honesty / no dead runs).
      const det = get().detectors.find((d) => d.key === key)
      if (det && !det.installed) return
    }
    const next = has ? cur.filter((k) => k !== key) : [...cur, key]
    set({ selectedDetectors: next })
    persist(get())
  },

  // ---- R61: results-by-detector + checkbox export selection ----
  // Ingest a detection payload that may carry MULTIPLE detectors. The backend
  // (§14 item 2) returns per-detector results either as `detection.detectors`
  // (array of { key/detector, ... }) or a `results_by_detector` map; a legacy
  // single-detector payload has neither and is stored under its own key so the
  // single-detector path is unchanged. Returns the normalized map.
  setResultsFromDetection: (detection) => {
    const map = normalizeResultsByDetector(detection)
    const keys = Object.keys(map)
    set({
      resultsByDetector: map,
      // Default every present detector to checked, so "Export selected" exports
      // everything until the user unchecks some (matches the single-result UX).
      exportSelection: keys,
    })
    return map
  },
  setExportSelection: (keys) => set({ exportSelection: Array.isArray(keys) ? keys : [] }),
  toggleExportSelection: (key) => {
    const cur = get().exportSelection || []
    const next = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]
    set({ exportSelection: next })
  },
  clearResults: () => set({ resultsByDetector: {}, exportSelection: [] }),

  // ---- R61: registry fetch + per-detector install/remove ----
  fetchDetectors: async () => {
    try {
      const res = await getDetectors()
      const rows = Array.isArray(res.data) ? res.data : (res.data?.detectors || [])
      set({ detectors: rows })
      // Prune any now-uninstalled detector from the run set (e.g. user removed it).
      const installed = new Set(rows.filter((d) => d.installed).map((d) => d.key))
      const pruned = (get().selectedDetectors || []).filter((k) => installed.has(k))
      if (pruned.length !== (get().selectedDetectors || []).length) {
        set({ selectedDetectors: pruned }); persist(get())
      }
      return rows
    } catch (e) {
      logger.warn('AiDetectionStore', 'fetchDetectors failed', e)
      return null
    }
  },

  installDetectorByKey: async (key) => {
    set((s) => ({
      detectorBusy: { ...s.detectorBusy, [key]: true },
      detectorError: { ...s.detectorError, [key]: null },
    }))
    try {
      await installDetector(key)
      // Poll the registry until this detector flips to installed (or errors).
      let misses = 0
      for (let i = 0; i < 600; i++) {
        const rows = await get().fetchDetectors()
        if (!rows) {
          if (++misses >= 3) break
          await new Promise((r) => setTimeout(r, 2000))
          continue
        }
        misses = 0
        const row = rows.find((d) => d.key === key)
        if (!row || row.installed || row.state === 'error') {
          if (row?.state === 'error') {
            set((s) => ({ detectorError: { ...s.detectorError, [key]: row.message || 'Install failed' } }))
          }
          break
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    } catch (e) {
      set((s) => ({ detectorError: { ...s.detectorError, [key]: e?.response?.data?.detail || e.message } }))
    } finally {
      set((s) => ({ detectorBusy: { ...s.detectorBusy, [key]: false } }))
    }
  },

  removeDetectorByKey: async (key) => {
    set((s) => ({
      detectorBusy: { ...s.detectorBusy, [key]: true },
      detectorError: { ...s.detectorError, [key]: null },
    }))
    try {
      await removeDetector(key)
      await get().fetchDetectors()
      // Drop the just-removed detector from the run set (it can no longer run).
      const next = (get().selectedDetectors || []).filter((k) => k !== key)
      set({ selectedDetectors: next }); persist(get())
    } catch (e) {
      set((s) => ({ detectorError: { ...s.detectorError, [key]: e?.response?.data?.detail || e.message } }))
    } finally {
      set((s) => ({ detectorBusy: { ...s.detectorBusy, [key]: false } }))
    }
  },

  fetchModelStatus: async () => {
    try {
      const res = await getAIDetectionModelStatus()
      // Surface a backend-reported download failure (state==='error') as
      // modelError — otherwise the button just re-enables with no reason shown.
      const err = res.data?.state === 'error' ? (res.data.message || 'Download failed') : null
      set({ modelStatus: res.data, modelError: err })
      return res.data
    } catch (e) {
      logger.warn('AiDetectionStore', 'model status failed', e)
      set({ modelError: e?.response?.data?.detail || e.message })
      return null
    }
  },

  downloadModel: async () => {
    set({ modelBusy: true, modelError: null })
    try {
      await downloadAIDetectionModel()
      // Poll until the background download settles. A transient status-fetch
      // failure (null) must not end the poll while the server is still
      // downloading — tolerate a few consecutive misses before giving up.
      let misses = 0
      for (let i = 0; i < 600; i++) {
        const st = await get().fetchModelStatus()
        if (!st) {
          if (++misses >= 3) break
          await new Promise((r) => setTimeout(r, 2000))
          continue
        }
        misses = 0
        if (st.state === 'installed' || st.state === 'error' || st.installed) break
        await new Promise((r) => setTimeout(r, 2000))
      }
    } catch (e) {
      set({ modelError: e?.response?.data?.detail || e.message })
    } finally {
      set({ modelBusy: false })
    }
  },

  deleteModel: async () => {
    set({ modelBusy: true, modelError: null })
    try {
      const res = await deleteAIDetectionModel()
      set({ modelStatus: res.data })
    } catch (e) {
      set({ modelError: e?.response?.data?.detail || e.message })
    } finally {
      set({ modelBusy: false })
    }
  },

  fetchRuntimeStatus: async () => {
    try {
      const res = await getAIDetectionRuntimeStatus()
      // Surface a backend-reported failure (state==='error') as runtimeError —
      // otherwise the button just re-enables with no reason shown.
      const err = res.data?.state === 'error' ? (res.data.message || 'Install failed') : null
      set({ runtimeStatus: res.data, runtimeError: err })
      // Keep the model card's deps_available view in sync (the model status
      // also reports deps_available; refresh it so the Download button enables
      // the moment a runtime install finishes).
      if (res.data?.deps_available) get().fetchModelStatus()
      return res.data
    } catch (e) {
      logger.warn('AiDetectionStore', 'runtime status failed', e)
      set({ runtimeError: e?.response?.data?.detail || e.message })
      return null
    }
  },

  fetchDiagnostics: async () => {
    try {
      const res = await getAIDetectionDiagnostics()
      set({ diagnostics: res.data })
      if (res.data?.runtime) {
        const rt = res.data.runtime
        const err = rt.state === 'error' ? (rt.message || 'Install failed') : null
        set({ runtimeStatus: rt, runtimeError: err })
      }
      return res.data
    } catch (e) {
      logger.warn('AiDetectionStore', 'diagnostics failed', e)
      return null
    }
  },

  installRuntime: async (variant = 'torch') => {
    set({ runtimeBusy: true, runtimeError: null })
    try {
      await installAIDetectionRuntime(variant)
      // Installing torch + transformers is a large download; poll generously
      // and refresh diagnostics each tick so the status bar + log stream live.
      let misses = 0
      for (let i = 0; i < 900; i++) {
        const d = await get().fetchDiagnostics()
        const st = d?.runtime || (await get().fetchRuntimeStatus())
        if (!st) {
          if (++misses >= 3) break
          await new Promise((r) => setTimeout(r, 1500))
          continue
        }
        misses = 0
        if (st.deps_available || st.state === 'error') break
        await new Promise((r) => setTimeout(r, 1500))
      }
    } catch (e) {
      set({ runtimeError: e?.response?.data?.detail || e.message })
    } finally {
      set({ runtimeBusy: false })
    }
  },
}))
