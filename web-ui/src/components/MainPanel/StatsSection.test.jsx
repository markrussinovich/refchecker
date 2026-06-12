import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StatsSection from './StatsSection'
import HealthBadge from './HealthBadge'

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

// HealthBadge animates the score with anime.js; stub it so the badge renders
// the final value synchronously and the tooltip counts are stable to assert.
vi.mock('animejs', () => ({
  default: (opts) => {
    if (opts && typeof opts.update === 'function') opts.update()
    if (opts && typeof opts.complete === 'function') opts.complete()
    return { pause: vi.fn() }
  },
}))

vi.mock('../../stores/useCheckStore', () => {
  const state = { statusFilter: [], setStatusFilter: vi.fn() }
  const useCheckStore = (selector) => selector ? selector(state) : state
  useCheckStore.getState = () => state
  return { useCheckStore }
})

// Capture the props the per-article walkthrough "video" (R24) is fed without
// drawing on a (jsdom-less) canvas. Each render records the latest props.
const animationProps = []
vi.mock('../Modals/ShareAnimationCanvas', () => ({
  default: (props) => {
    animationProps.push(props)
    return <div data-testid="stats-video" />
  },
}))

// Helper to build a reference object
const makeRef = (status, { errors = [], warnings = [], ...rest } = {}) => ({
  status,
  errors,
  warnings,
  ...rest,
})

describe('StatsSection warning count excludes refs that also have errors', () => {
  it('should not double-count refs with both errors and warnings', () => {
    // 3 refs with real errors; 2 of those ALSO have warnings
    // 2 refs with warnings-only (no errors)
    // 1 verified ref
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
      makeRef('warning', {
        warnings: [{ message: 'year off by 1' }],
      }),
      makeRef('warning', {
        warnings: [{ message: 'venue not found' }],
      }),
      makeRef('verified'),
    ]

    const stats = {
      total_refs: 6,
      processed_refs: 6,
      errors_count: 3,
      warnings_count: 4,
      suggestions_count: 0,
      unverified_count: 0,
      hallucination_count: 0,
    }

    render(
      <StatsSection
        stats={stats}
        isComplete={true}
        references={references}
        paperTitle="Test Paper"
        paperSource="https://example.com/paper"
      />
    )

    // The error badge should show 3 (refs with errors)
    // The warning badge should show 2 (refs with warnings ONLY, not 4)
    // The verified badge should show 1
    const badges = screen.getAllByRole('button')
    // Verified, Errors, Warnings badges (+ Export button)
    // Find the text content of all badge-like buttons
    const badgeTexts = badges.map(b => b.textContent.trim())

    // Verified=1, Errors=3, Warnings=2
    expect(badgeTexts).toContain('1')
    expect(badgeTexts).toContain('3')
    expect(badgeTexts).toContain('2')
    // Warnings should NOT show 4 (inclusive would count refs with both errors+warnings)
    expect(badgeTexts).not.toContain('4')
  })
})

// R16 (F2): the Citation-health badge and the Summary chips must agree —
// HealthBadge.computeScore must bucket refs warnings-ONLY (a ref with both an
// error and a warning is an error ref, not also a warning ref), exactly like
// the StatsSection chips. Before the fix the badge tooltip read 4 warnings
// where the chips showed 2.
describe('HealthBadge counts agree with StatsSection chip counts (R16)', () => {
  // Shared fixture: 3 error refs (2 of them also carry a warning),
  // 2 warning-only refs, 1 verified ref. Chips => Errors 3 · Warnings 2.
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
  ]

  it('reports the same error/warning ref counts the StatsSection chips show', () => {
    // HealthBadge in isolation — read its tooltip, which spells out the
    // per-status breakdown ("… · N warning(s) · M error(s) …").
    const { container, unmount } = render(<HealthBadge references={references} />)
    const tooltip = container.querySelector('span[title]').getAttribute('title')
    const warnFromBadge = Number(/(\d+)\s+warning/.exec(tooltip)?.[1])
    const errFromBadge = Number(/(\d+)\s+error/.exec(tooltip)?.[1])
    unmount()

    // The badge buckets warnings-only and errors-with-priority, so for this
    // fixture: 3 errors, 2 warnings (NOT 4 — the both-error+warning refs are
    // counted as errors only).
    expect(errFromBadge).toBe(3)
    expect(warnFromBadge).toBe(2)

    // StatsSection chips for the SAME references must match exactly.
    render(
      <StatsSection
        stats={{ total_refs: 6, processed_refs: 6 }}
        isComplete={true}
        references={references}
        paperTitle="Agreement Paper"
        paperSource="https://example.com/agree"
      />
    )
    // Row-1 Errors badge ("N references with errors") and row-1 Warnings
    // badge ("N references with warnings only") — both rows now read
    // "references with <issue>", so the error title appears on the row-2
    // chip too; assert at least one carrier shows the badge's count.
    const errChips = screen.getAllByTitle(/references? with errors/i)
    const warnChip = screen.getByTitle(/references? with warnings only/i)
    expect(errChips.some(c => within(c).queryByText(String(errFromBadge)))).toBe(true)
    expect(within(warnChip).getByText(String(warnFromBadge))).toBeTruthy()
  })

  // The common unverified case: a ref whose ONLY error entry is
  // {error_type:'unverified'} ("could not verify / not found"). The chips
  // exclude it from the error bucket (getEffectiveReferenceStatus treats
  // unverified-only errors as NOT errors), so the badge must too. Before the
  // fix, HealthBadge's raw `(errors||[]).length > 0` test counted it as an
  // error ref → badge "1 error" vs chip "0 references with errors".
  it('does not count an unverified-only ref as an error (agrees with chips)', () => {
    const refs = [
      makeRef('error', { errors: [{ error_type: 'author', message: 'author mismatch' }] }),
      makeRef('unverified', { errors: [{ error_type: 'unverified', message: 'not found' }] }),
    ]

    const { container, unmount } = render(<HealthBadge references={refs} />)
    const tooltip = container.querySelector('span[title]').getAttribute('title')
    const errFromBadge = Number(/(\d+)\s+error/.exec(tooltip)?.[1])
    const warnFromBadge = Number(/(\d+)\s+warning/.exec(tooltip)?.[1])
    unmount()

    // 1 genuine error ref, the unverified-only ref is NOT an error.
    expect(errFromBadge).toBe(1)
    expect(warnFromBadge).toBe(0)

    // StatsSection chips for the SAME refs (isComplete=true so the unverified
    // ref finalizes) must match.
    render(
      <StatsSection
        stats={{ total_refs: 2, processed_refs: 2 }}
        isComplete={true}
        references={refs}
        paperTitle="Unverified Paper"
        paperSource="https://example.com/unverified"
      />
    )
    const errChips = screen.getAllByTitle(/references? with errors/i)
    expect(errChips.some(c => within(c).queryByText(String(errFromBadge)))).toBe(true)
  })

  // A hallucinated ref carries its error entries as EVIDENCE of the
  // hallucination. The chips suppress those (counting the ref only in the
  // hallucination bucket); the badge must too. Before the fix the
  // error/warning block ran unconditionally, so the hallucinated ref bumped
  // BOTH halluc and errors → badge "1 error" vs chip "0 references with errors".
  it('does not count a hallucinated ref with error evidence as an error', () => {
    const refs = [
      makeRef('error', { errors: [{ error_type: 'title', message: 'title mismatch' }] }),
      makeRef('hallucination', {
        title: 'A fabricated paper that does not exist',
        authors: ['Nobody'],
        errors: [{ error_type: 'not_found', message: 'no matching record found' }],
        hallucination_assessment: { verdict: 'LIKELY' },
      }),
    ]

    const { container, unmount } = render(<HealthBadge references={refs} />)
    const tooltip = container.querySelector('span[title]').getAttribute('title')
    const errFromBadge = Number(/(\d+)\s+error/.exec(tooltip)?.[1])
    const warnFromBadge = Number(/(\d+)\s+warning/.exec(tooltip)?.[1])
    unmount()

    // Only the genuine error ref is an error; the hallucinated ref's error
    // entry is evidence, not a counted error.
    expect(errFromBadge).toBe(1)
    expect(warnFromBadge).toBe(0)

    render(
      <StatsSection
        stats={{ total_refs: 2, processed_refs: 2 }}
        isComplete={true}
        references={refs}
        paperTitle="Hallucination Paper"
        paperSource="https://example.com/halluc"
      />
    )
    const errChips = screen.getAllByTitle(/references? with errors/i)
    expect(errChips.some(c => within(c).queryByText(String(errFromBadge)))).toBe(true)
  })
})

// R48: ONE canonical count/health across the Summary badge AND the report card.
// Both surfaces must read the same buildReferenceSummary buckets so a check can
// never show e.g. badge 30 verified / 8 warn while the report card shows 29 / 9.
// This pins the badge<->report-card agreement (extends R16) including the
// verified-vs-warning boundary that produced the off-by-one.
describe('HealthBadge and StatsSection share one canonical summary (R48)', () => {
  // 2 verified + 1 warning-only + 1 error-with-also-a-warning. Canonical buckets
  // (getEffectiveReferenceStatus precedence): verified 2, warnings 1, errors 1.
  const references = [
    makeRef('verified'),
    makeRef('verified'),
    makeRef('warning', { warnings: [{ message: 'venue differs' }] }),
    makeRef('error', {
      errors: [{ error_type: 'title', message: 'title mismatch' }],
      warnings: [{ message: 'also a warning' }],
    }),
  ]

  it('badge tooltip counts equal the report-card chip counts', () => {
    const { container, unmount } = render(<HealthBadge references={references} />)
    const tooltip = container.querySelector('span[title]').getAttribute('title')
    const verFromBadge = Number(/(\d+)\s+verified/.exec(tooltip)?.[1])
    const warnFromBadge = Number(/(\d+)\s+warning/.exec(tooltip)?.[1])
    const errFromBadge = Number(/(\d+)\s+error/.exec(tooltip)?.[1])
    unmount()

    // Canonical: verified 2, warnings 1 (the error+warning ref is an error ref
    // only), errors 1.
    expect(verFromBadge).toBe(2)
    expect(warnFromBadge).toBe(1)
    expect(errFromBadge).toBe(1)

    render(
      <StatsSection
        stats={{ total_refs: 4, processed_refs: 4 }}
        isComplete={true}
        references={references}
        paperTitle="Canonical Paper"
        paperSource="https://example.com/canonical"
      />
    )
    // Report-card chips read the same canonical buckets.
    const verChip = screen.getByTitle(/references? fully verified/i)
    const warnChip = screen.getByTitle(/references? with warnings only/i)
    const errChips = screen.getAllByTitle(/references? with errors/i)
    expect(within(verChip).getByText(String(verFromBadge))).toBeTruthy()
    expect(within(warnChip).getByText(String(warnFromBadge))).toBeTruthy()
    expect(errChips.some(c => within(c).queryByText(String(errFromBadge)))).toBe(true)
  })

  it('renders one citation-health % for the whole report (badge inside the card)', () => {
    // The badge passed in as the StatsSection healthBadge prop is the SAME
    // component instance the standalone badge renders — one source, one %.
    render(
      <StatsSection
        stats={{ total_refs: 4, processed_refs: 4 }}
        isComplete={true}
        references={references}
        paperTitle="Canonical Paper"
        paperSource="https://example.com/canonical"
        healthBadge={<HealthBadge references={references} />}
      />
    )
    const health = screen.getByTitle(/verified .* warning .* error/i)
    expect(health.textContent).toMatch(/Citation health/)
    expect(health.textContent).toMatch(/%/)
  })
})

describe('StatsSection hallucination count', () => {
  it('uses backend processed_refs instead of deriving progress from status buckets', () => {
    const references = [
      ...Array.from({ length: 24 }, () => makeRef('verified')),
      ...Array.from({ length: 14 }, () => makeRef('error', {
        errors: [{ error_type: 'author', message: 'author mismatch' }],
      })),
      ...Array.from({ length: 8 }, () => makeRef('warning', {
        warnings: [{ message: 'venue differs' }],
      })),
      ...Array.from({ length: 4 }, () => makeRef('unverified', {
        errors: [{ error_type: 'unverified', message: 'not found' }],
        hallucination_check_pending: true,
      })),
    ]

    render(
      <StatsSection
        stats={{
          total_refs: 59,
          processed_refs: 50,
          refs_verified: 24,
          refs_with_errors: 14,
          refs_with_warnings_only: 8,
          unverified_count: 4,
          hallucination_count: 0,
        }}
        isComplete={false}
        references={references}
        paperTitle="Test Paper"
        paperSource="https://example.com/paper"
      />
    )

    expect(screen.getByText('50/59 checked')).toBeTruthy()
    expect(screen.getByText('of 50')).toBeTruthy()
    expect(screen.queryByTitle(/could not be verified/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /unverified/i })).toBeNull()
  })

  it('does not count LLM-found matching metadata as hallucinated', () => {
    const references = [
      makeRef('hallucination', {
        title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
        year: 2024,
        hallucination_assessment: {
          verdict: 'LIKELY',
          link: 'https://arxiv.org/abs/2405.18123',
          found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
          found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
          found_year: '2024',
        },
      }),
    ]

    render(
      <StatsSection
        stats={{ total_refs: 1, processed_refs: 1, hallucination_count: 1 }}
        isComplete={true}
        references={references}
        paperTitle="Test Paper"
        paperSource="https://example.com/paper"
      />
    )

    expect(screen.queryByTitle(/likely hallucinated/i)).toBeNull()
  })
})

// Z3 (BUTTON_DESIGN §1.0/§4.7/§1.3, R33/R52): the "Filter by issue" chips must
// read as part of the action-control family — the ONE 8px radius (never
// 9999px / rounded-full), and click-state stability (no scale/shadow/ring that
// reflows the chip on hover or select). They are toggles, so they expose
// aria-pressed for assistive tech.
describe('StatsSection filter chips follow the control design system (Z3)', () => {
  const references = [
    makeRef('error', { errors: [{ error_type: 'author', message: 'author mismatch' }] }),
    makeRef('error', { errors: [{ error_type: 'title', message: 'title mismatch' }] }),
    makeRef('warning', { warnings: [{ message: 'venue differs' }] }),
    makeRef('verified'),
  ]

  it('renders 8px-radius, aria-pressed chips with no scale/shadow hover geometry', () => {
    render(
      <StatsSection
        stats={{ total_refs: 4, processed_refs: 4 }}
        isComplete={true}
        references={references}
        paperTitle="Filter Chip Paper"
        paperSource="https://example.com/chips"
      />
    )
    // The toggle filter chips are the buttons carrying aria-pressed.
    const chips = screen.getAllByRole('button').filter(b => b.hasAttribute('aria-pressed'))
    expect(chips.length).toBeGreaterThan(0)
    for (const chip of chips) {
      // The ONE radius — never the old pill 9999px.
      expect(chip.style.borderRadius).toBe('var(--control-radius)')
      expect(chip.className).not.toMatch(/rounded-full/)
      // No geometry/shadow change on state (R52): only colours transition.
      expect(chip.className).not.toMatch(/scale-/)
      expect(chip.className).not.toMatch(/shadow/)
      // Resting (unselected) toggle state is exposed honestly.
      expect(chip.getAttribute('aria-pressed')).toBe('false')
    }
  })
})

// The animated walkthrough "video" must live ONLY in the Share popup, never
// inline in the Summary stats (reverts R24's stats-page placement per user
// request). The mocked ShareAnimationCanvas renders a `stats-video` testid, so
// asserting its absence guards against the canvas leaking back into this view.
describe('StatsSection does NOT render the walkthrough video inline', () => {
  it('renders no ShareAnimationCanvas in the stats summary', () => {
    animationProps.length = 0
    render(
      <StatsSection
        stats={{ total_refs: 7, processed_refs: 7 }}
        isComplete={true}
        references={[makeRef('verified'), makeRef('error', { errors: [{ error_type: 'year' }] })]}
        paperTitle="Video Paper"
        paperSource="https://example.com/video"
      />
    )
    expect(screen.queryByTestId('stats-video')).toBeNull()
    expect(animationProps.length).toBe(0)
  })
})
