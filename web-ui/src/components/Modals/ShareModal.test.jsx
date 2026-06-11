import { render, cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// R45 acceptance: a vitest comparing the SHARE video counts to the
// StatsSection video counts for the SAME article. ShareModal and StatsSection
// each independently derive the per-article video `stats` (style-aware
// buildReferenceSummary → { total, verified, warnings, errors+hallucinated }).
// This test renders BOTH surfaces against identical inputs, captures the
// `stats` prop each one feeds to ShareAnimationCanvas, and asserts they are
// deep-equal — so any future drift in either grouping fails CI.

// --- Capture every ShareAnimationCanvas render -----------------------------
// ShareModal imports it as './ShareAnimationCanvas' and StatsSection imports
// it as '../Modals/ShareAnimationCanvas'; both resolve to the SAME physical
// module, so a single mock catches both surfaces. We snapshot the array after
// each separate render to attribute the props to the surface just rendered.
const canvasProps = []
vi.mock('./ShareAnimationCanvas', () => ({
  default: (props) => {
    canvasProps.push(props)
    return <div data-testid="share-video" />
  },
}))
// `lastCanvasStats()` returns the stats of the most recent canvas render.
const lastCanvasStats = () => canvasProps[canvasProps.length - 1]?.stats

// StatsSection animates HealthBadge with anime.js; resolve it synchronously.
vi.mock('animejs', () => ({
  default: (opts) => {
    if (opts && typeof opts.update === 'function') opts.update()
    if (opts && typeof opts.complete === 'function') opts.complete()
    return { pause: vi.fn() }
  },
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

// ShareModal's API surface — never called in this render path, but imported.
vi.mock('../../utils/api', () => ({
  exportCheckFile: vi.fn(),
  exportBatchFile: vi.fn(),
  publishCheck: vi.fn(),
}))

// --- Store mocks faithful to both surfaces' selector usage -----------------
// ShareModal calls useCheckStore() with NO selector (whole store) and reads
// `.references` / `.aiDetection` / `.stats`. StatsSection calls it WITH a
// selector for statusFilter/setStatusFilter and uses getState(). The mock must
// honour both call shapes.
const checkState = {
  references: [],
  aiDetection: null,
  stats: {},
  statusFilter: [],
  setStatusFilter: vi.fn(),
  clearStatusFilter: vi.fn(),
}
vi.mock('../../stores/useCheckStore', () => {
  const useCheckStore = (selector) => (selector ? selector(checkState) : checkState)
  useCheckStore.getState = () => checkState
  return { useCheckStore }
})

// ShareModal pulls the article's references/AI/status from the selected check.
let historyState = { selectedCheck: null }
vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = (selector) => (selector ? selector(historyState) : historyState)
  useHistoryStore.getState = () => historyState
  return { useHistoryStore }
})

// Both surfaces read the active citation style from the same store; the same
// format must drive both so the style-aware filtering is identical.
let styleState = { format: 'ieee' }
vi.mock('../../stores/useStyleStore', () => {
  const useStyleStore = (selector) => (selector ? selector(styleState) : styleState)
  useStyleStore.getState = () => styleState
  return { useStyleStore }
})

import ShareModal from './ShareModal'
import StatsSection from '../MainPanel/StatsSection'

const makeRef = (status, { errors = [], warnings = [], ...rest } = {}) => ({
  status,
  errors,
  warnings,
  ...rest,
})

// A spread of statuses that exercises every bucket the grouping touches:
// 3 error refs (2 also warn), 2 warning-only, 1 verified, 1 hallucinated.
// Expected grouped video stats: total 7, verified 1, warnings 2, errors 3+1=4.
const references = [
  makeRef('error', {
    errors: [{ error_type: 'author', message: 'author mismatch' }],
    warnings: [{ message: 'year is approximate' }],
  }),
  makeRef('error', {
    errors: [{ error_type: 'title', message: 'title mismatch' }],
    warnings: [{ message: 'venue differs' }],
  }),
  makeRef('error', {
    errors: [{ error_type: 'year', message: 'wrong year' }],
  }),
  makeRef('warning', { warnings: [{ message: 'year off by 1' }] }),
  makeRef('warning', { warnings: [{ message: 'venue not found' }] }),
  makeRef('verified'),
  makeRef('hallucination', {
    title: 'A fabricated paper that does not exist',
    authors: ['Nobody'],
    hallucination_assessment: { verdict: 'LIKELY' },
  }),
]

const stats = { total_refs: 7, processed_refs: 7 }

// Render the share surface in isolation and return the stats it fed the canvas.
function renderShareStats() {
  canvasProps.length = 0
  render(<ShareModal checkId={42} title="Parity Paper" onClose={() => {}} />)
  const s = lastCanvasStats()
  cleanup()
  return s
}

// Render the stats surface in isolation; optionally read the visible chips
// before tearing it down. Returns { stats, chips }.
function renderStatsSection(readChips = false) {
  canvasProps.length = 0
  render(
    <StatsSection
      stats={stats}
      isComplete={true}
      references={references}
      paperTitle="Parity Paper"
      paperSource="https://example.com/parity"
      aiBand="high"
      aiScore={0.91}
      videoKey="statvid-42"
    />
  )
  const s = lastCanvasStats()
  let chips = null
  if (readChips) {
    const verChip = screen.getByTitle(/references? fully verified/i)
    const warnChip = screen.getByTitle(/references? with warnings only/i)
    const errChips = screen.getAllByTitle(/references? with errors/i)
    chips = {
      verified: Number(within(verChip).getByText(/^\d+$/).textContent),
      warnings: Number(within(warnChip).getByText(/^\d+$/).textContent),
      errors: errChips
        .map((c) => within(c).queryByText(/^\d+$/))
        .filter(Boolean)
        .map((n) => Number(n.textContent))[0],
    }
  }
  cleanup()
  return { stats: s, chips }
}

beforeEach(() => {
  canvasProps.length = 0
  checkState.statusFilter = []
  historyState = {
    selectedCheck: {
      status: 'completed',
      references,
      ai_detection: { band: 'high', overall_score: 0.91 },
    },
  }
  styleState = { format: 'ieee' }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// Bug B / R45: the share card/video must show the SAME counts the user sees in
// the StatsSection results bar. StatsSection no longer renders the animation
// inline (it lives only in the Share popup), so parity is now measured against
// the VISIBLE bar chips. Crucially, errors are NOT grouped with hallucinated —
// the bar's errors chip is references.errors only (hallucinated is its own
// bucket), so grouping made the share read 9 vs the bar's 7.
describe('ShareModal video counts equal the StatsSection results bar (R45 / Bug-B)', () => {
  it('feeds ShareAnimationCanvas the SAME {verified,warnings,errors} the bar shows', () => {
    const { chips } = renderStatsSection(true)
    const shareStats = renderShareStats()

    expect(shareStats).toBeTruthy()
    // Equal to the visible bar chips — errors un-grouped (3, not 4).
    expect(shareStats.verified).toBe(chips.verified) // 1
    expect(shareStats.warnings).toBe(chips.warnings) // 2
    expect(shareStats.errors).toBe(chips.errors)     // 3 (hallucinated NOT folded in)
    expect(shareStats).toEqual({ total: 7, verified: 1, warnings: 2, errors: 3 })
  })

  it('stays equal to the bar when the citation style changes', () => {
    // Both consume the same useStyleStore.format, so a style change applies to
    // both surfaces; the share counts must still equal the bar chips.
    styleState = { format: 'apa' }

    const { chips } = renderStatsSection(true)
    const shareStats = renderShareStats()

    expect(shareStats.verified).toBe(chips.verified)
    expect(shareStats.warnings).toBe(chips.warnings)
    expect(shareStats.errors).toBe(chips.errors)
  })
})
