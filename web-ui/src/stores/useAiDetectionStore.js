import { create } from 'zustand'
import { logger } from '../utils/logger'
import {
  getAIDetectionModelStatus,
  downloadAIDetectionModel,
  deleteAIDetectionModel,
  getAIDetectionRuntimeStatus,
  installAIDetectionRuntime,
  getAIDetectionDiagnostics,
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
    }))
  } catch (e) {
    logger.warn('AiDetectionStore', 'Failed to persist preferences', e)
  }
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

  setEnabled: (enabled) => { set({ enabled }); persist(get()) },
  setBackend: (backend) => { set({ backend }); persist(get()) },
  setService: (service) => { set({ service }); persist(get()) },
  setConsent: (consent) => { set({ consent }); persist(get()) },

  fetchModelStatus: async () => {
    try {
      const res = await getAIDetectionModelStatus()
      set({ modelStatus: res.data, modelError: null })
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
