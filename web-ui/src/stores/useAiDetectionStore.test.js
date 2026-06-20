import { describe, it, expect, beforeEach, vi } from 'vitest'

// R61 (I2) — multi-detector store: registry fetch + per-detector install/remove,
// run-selection of INSTALLED detectors only, results-by-detector ingestion, and
// checkbox-export selection. The api module is fully mocked so no network runs.

const mockGetDetectors = vi.fn()
const mockInstallDetector = vi.fn(() => Promise.resolve({ data: {} }))
const mockRemoveDetector = vi.fn(() => Promise.resolve({ data: {} }))

vi.mock('../utils/api', () => ({
  // AI-detection model/runtime lifecycle (unused here but imported by the store)
  getAIDetectionModelStatus: vi.fn(() => Promise.resolve({ data: {} })),
  downloadAIDetectionModel: vi.fn(() => Promise.resolve({ data: {} })),
  deleteAIDetectionModel: vi.fn(() => Promise.resolve({ data: {} })),
  getAIDetectionRuntimeStatus: vi.fn(() => Promise.resolve({ data: {} })),
  installAIDetectionRuntime: vi.fn(() => Promise.resolve({ data: {} })),
  getAIDetectionDiagnostics: vi.fn(() => Promise.resolve({ data: {} })),
  // R61 registry endpoints
  getDetectors: (...a) => mockGetDetectors(...a),
  installDetector: (...a) => mockInstallDetector(...a),
  removeDetector: (...a) => mockRemoveDetector(...a),
}))

const REGISTRY = [
  { key: 'desklib', label: 'Desklib', repo: 'desklib/ai-text-detector-v1.01', arch: 'DeBERTa-v3', tier: 1, license: 'MIT', size_bytes: 800 * 1024 * 1024, installed: true },
  { key: 'superannotate', label: 'SuperAnnotate', repo: 'SuperAnnotate/ai-detector', arch: 'RoBERTa-Large', tier: 1, license: 'SAIPL', size_bytes: 500 * 1024 * 1024, installed: false },
  { key: 'binoculars', label: 'Binoculars', arch: 'metric zero-shot', tier: 2, heavy: true, license: 'MIT', size_bytes: 5 * 1024 * 1024 * 1024, installed: false, available: true },
]

beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  let ls = {}
  localStorage.getItem.mockImplementation((k) => ls[k] ?? null)
  localStorage.setItem.mockImplementation((k, v) => { ls[k] = String(v) })
  localStorage.removeItem.mockImplementation((k) => { delete ls[k] })
  localStorage.clear.mockImplementation(() => { ls = {} })
  localStorage.clear()
  mockGetDetectors.mockResolvedValue({ data: { detectors: REGISTRY } })
})

describe('useAiDetectionStore — registry + install state', () => {
  it('fetchDetectors loads the registry with per-detector install states', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    const rows = useAiDetectionStore.getState().detectors
    expect(rows.map((d) => d.key)).toEqual(['desklib', 'superannotate', 'binoculars'])
    expect(rows.find((d) => d.key === 'desklib').installed).toBe(true)
    expect(rows.find((d) => d.key === 'superannotate').installed).toBe(false)
  })

  it('installDetectorByKey installs then polls the registry until installed', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    // After install, the registry reports superannotate as installed.
    mockGetDetectors.mockResolvedValue({
      data: { detectors: REGISTRY.map((d) => d.key === 'superannotate' ? { ...d, installed: true } : d) },
    })
    await useAiDetectionStore.getState().installDetectorByKey('superannotate')
    expect(mockInstallDetector).toHaveBeenCalledWith('superannotate')
    expect(useAiDetectionStore.getState().detectors.find((d) => d.key === 'superannotate').installed).toBe(true)
    expect(useAiDetectionStore.getState().detectorBusy.superannotate).toBe(false)
  })

  it('removeDetectorByKey removes and drops it from the run selection', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    useAiDetectionStore.getState().setSelectedDetectors(['desklib'])
    // After remove, the registry reports desklib uninstalled.
    mockGetDetectors.mockResolvedValue({
      data: { detectors: REGISTRY.map((d) => d.key === 'desklib' ? { ...d, installed: false } : d) },
    })
    await useAiDetectionStore.getState().removeDetectorByKey('desklib')
    expect(mockRemoveDetector).toHaveBeenCalledWith('desklib')
    expect(useAiDetectionStore.getState().selectedDetectors).not.toContain('desklib')
  })
})

describe('useAiDetectionStore — run selection (installed detectors only)', () => {
  it('setSelectedDetectors keeps only installed detectors', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    // superannotate is NOT installed — it must be filtered out.
    useAiDetectionStore.getState().setSelectedDetectors(['desklib', 'superannotate'])
    expect(useAiDetectionStore.getState().selectedDetectors).toEqual(['desklib'])
  })

  it('toggleSelectedDetector refuses to add an uninstalled detector', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    useAiDetectionStore.getState().toggleSelectedDetector('superannotate') // not installed
    expect(useAiDetectionStore.getState().selectedDetectors).not.toContain('superannotate')
    useAiDetectionStore.getState().toggleSelectedDetector('desklib') // installed
    expect(useAiDetectionStore.getState().selectedDetectors).toContain('desklib')
  })

  it('persists selectedDetectors to localStorage', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    await useAiDetectionStore.getState().fetchDetectors()
    useAiDetectionStore.getState().setSelectedDetectors(['desklib'])
    const saved = JSON.parse(localStorage.getItem('refchecker.aiDetection.v1'))
    expect(saved.selectedDetectors).toEqual(['desklib'])
  })
})

describe('useAiDetectionStore — results-by-detector + export selection', () => {
  it('normalizeResultsByDetector handles the multi-detector array shape', async () => {
    const { normalizeResultsByDetector } = await import('./useAiDetectionStore')
    const map = normalizeResultsByDetector({
      detectors: [
        { key: 'desklib', band: 'high', overall_score: 0.9 },
        { key: 'superannotate', band: 'low', overall_score: 0.1 },
      ],
    })
    expect(Object.keys(map)).toEqual(['desklib', 'superannotate'])
    expect(map.desklib.band).toBe('high')
  })

  it('a legacy single-detector payload is keyed under its own model id (no fabricated entries)', async () => {
    const { normalizeResultsByDetector } = await import('./useAiDetectionStore')
    const map = normalizeResultsByDetector({ band: 'medium', overall_score: 0.5, model_version: 'local:desklib/x' })
    expect(Object.keys(map)).toEqual(['local:desklib/x'])
    expect(map['local:desklib/x'].band).toBe('medium')
  })

  it('setResultsFromDetection default-checks every present detector for export', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    useAiDetectionStore.getState().setResultsFromDetection({
      detectors: [{ key: 'desklib', band: 'high' }, { key: 'mage', band: 'low' }],
    })
    expect(useAiDetectionStore.getState().exportSelection.sort()).toEqual(['desklib', 'mage'])
  })

  it('toggleExportSelection includes/excludes exactly the toggled detector', async () => {
    const { useAiDetectionStore } = await import('./useAiDetectionStore')
    useAiDetectionStore.getState().setResultsFromDetection({
      detectors: [{ key: 'desklib', band: 'high' }, { key: 'mage', band: 'low' }],
    })
    useAiDetectionStore.getState().toggleExportSelection('mage') // uncheck mage
    expect(useAiDetectionStore.getState().exportSelection).toEqual(['desklib'])
    expect(useAiDetectionStore.getState().exportSelection).not.toContain('mage')
  })
})
