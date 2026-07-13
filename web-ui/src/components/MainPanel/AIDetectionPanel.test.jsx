import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

// R61 — DocumentViewer is heavy + irrelevant here; the real AIDetectionVisuals
// IS kept so the multi-detector comparison + "Export selected" button render.
// downloadAsFile is spied so the checkbox-export test asserts the emitted
// content + format without touching the Blob/DOM download path.
vi.mock('./DocumentViewer', () => ({ default: () => <div data-testid="doc-viewer" /> }))
vi.mock('../../utils/tauriBridge', () => ({ isTauri: () => false, openExternal: vi.fn() }))
const mockDownloadAsFile = vi.fn()
vi.mock('../../utils/formatters', () => ({ downloadAsFile: (...a) => mockDownloadAsFile(...a) }))

import AIDetectionPanel, { buildViewerSpans, serializeDetectorExport, buildAgreementRows } from './AIDetectionPanel'

// R29 (S6) — every span handed to the document viewer must carry a `refId` so
// the on-hover bar + in-document link work for ALL spans, including AI spans
// (which previously had none, making them silently non-clickable). AI/flagged
// sentences don't map to a bibliography entry, so they get a stable
// self-referential `ai:<index>` id keyed to their position in the located-span
// list. A real refId on a corroborated span is preserved as-is.

const detection = {
  spans: [
    { quote: 'A corroborated flagged passage of sufficient length.', model_score: 0.9 },
    { quote: 'Another corroborated passage already carrying a refId.', refId: '7' },
  ],
  per_page_scores: [
    {
      page: 1,
      sentences: [
        { text: 'A page-by-page flagged sentence of enough length to keep.', score: 0.8 },
      ],
    },
  ],
  top_ai_sentences: [
    { text: 'A distinct top AI sentence that is its own viewer span.', score: 0.95 },
  ],
}

describe('buildViewerSpans refId population (R29)', () => {
  it('gives every span a refId, incl. AI spans, and preserves an existing refId', () => {
    const { viewerSpans } = buildViewerSpans(detection)

    expect(viewerSpans.length).toBeGreaterThanOrEqual(3)
    // Every span carries a refId — none is null/undefined.
    for (const sp of viewerSpans) {
      expect(sp.refId == null).toBe(false)
    }
    // The corroborated span with no id gets a self-referential ai:<index>.
    expect(viewerSpans[0].refId).toBe('ai:0')
    expect(viewerSpans[0].kind).toBe('ai')
    // A span that already had a real refId keeps it untouched.
    expect(viewerSpans[1].refId).toBe('7')
  })

  it('appended sentence spans also carry a self-referential refId', () => {
    const { viewerSpans, indexByText } = buildViewerSpans(detection)
    const idx = indexByText.get('a distinct top ai sentence that is its own viewer span.')
    expect(idx).toBeGreaterThanOrEqual(2)
    expect(viewerSpans[idx].refId).toBe(`ai:${idx}`)
    expect(viewerSpans[idx].kind).toBe('ai')
    // The real per-sentence score is carried (no fabricated value).
    expect(viewerSpans[idx].model_score).toBe(0.95)
  })

  it('tolerates a null detection without throwing', () => {
    const { viewerSpans, indexByText } = buildViewerSpans(null)
    expect(viewerSpans).toEqual([])
    expect(indexByText.size).toBe(0)
  })
})

// R61 (I2) — checkbox-export serializer: emits ONLY the checked detectors'
// results in the existing MD/CSV/JSON shapes, with no fabricated scores.
describe('serializeDetectorExport — export only the checked detectors (R61)', () => {
  const results = {
    desklib: { label: 'Desklib', band: 'high', overall_score: 0.9 },
    superannotate: { label: 'SuperAnnotate', band: 'low', overall_score: 0.1 },
    mage: { label: 'MAGE', band: 'inconclusive' }, // abstained — no score
  }

  it('JSON contains exactly the checked detectors and nothing else', () => {
    const json = JSON.parse(serializeDetectorExport(results, ['desklib', 'mage'], 'json'))
    const keys = json.detectors.map((d) => d.key)
    expect(keys).toEqual(['desklib', 'mage'])
    expect(keys).not.toContain('superannotate')
    // The abstaining detector carries a null score (never a fabricated number).
    expect(json.detectors.find((d) => d.key === 'mage').score).toBeNull()
  })

  it('CSV has one data row per checked detector', () => {
    const csv = serializeDetectorExport(results, ['desklib'], 'csv')
    const lines = csv.trim().split('\n')
    expect(lines[0]).toBe('detector_key,label,band,score')
    expect(lines).toHaveLength(2) // header + 1 row
    expect(lines[1]).toContain('desklib')
    expect(csv).not.toContain('superannotate')
  })

  it('MD renders only the checked detectors as table rows', () => {
    const md = serializeDetectorExport(results, ['desklib', 'superannotate'], 'md')
    expect(md).toContain('| Desklib | high | 90 |')
    expect(md).toContain('| SuperAnnotate | low | 10 |')
    expect(md).not.toContain('MAGE')
  })
})

// R61 — the multi-detector panel renders the comparison + fires the export with
// exactly the checked detectors; a single-detector payload renders unchanged.
const multiDetection = {
  band: 'high',
  overall_score: 0.9,
  summary: 'Two detectors ran.',
  disclaimer: 'Advisory only.',
  detectors: [
    { key: 'desklib', label: 'Desklib', band: 'high', overall_score: 0.9 },
    { key: 'superannotate', label: 'SuperAnnotate', band: 'low', overall_score: 0.1 },
  ],
}

describe('AIDetectionPanel — multi-detector comparison + checkbox export (R61)', () => {
  it('renders the comparison table when the detection carries ≥2 detectors', () => {
    render(<AIDetectionPanel detection={multiDetection} checkId={5} />)
    expect(screen.getByTestId('detector-comparison')).toBeInTheDocument()
    expect(screen.getByText('Desklib')).toBeInTheDocument()
    expect(screen.getByText('SuperAnnotate')).toBeInTheDocument()
  })

  it('"Export selected" downloads only the checked detectors', () => {
    mockDownloadAsFile.mockClear()
    render(<AIDetectionPanel detection={multiDetection} checkId={5} />)
    // Both start checked; uncheck superannotate.
    fireEvent.click(screen.getByTestId('export-check-superannotate'))
    fireEvent.click(screen.getByRole('button', { name: /Export selected/i }))
    expect(mockDownloadAsFile).toHaveBeenCalledTimes(1)
    const [content] = mockDownloadAsFile.mock.calls[0]
    const parsed = JSON.parse(content)
    expect(parsed.detectors.map((d) => d.key)).toEqual(['desklib'])
  })

  it('a single-detector payload renders no comparison table (backward compat)', () => {
    const single = { band: 'medium', overall_score: 0.5, summary: 's', disclaimer: 'd', model_version: 'local:desklib/x' }
    render(<AIDetectionPanel detection={single} checkId={5} />)
    expect(screen.queryByTestId('detector-comparison')).toBeNull()
  })
})

// R61 (I2) — the FE must adapt the backend's REAL comparison summary shape
// (multi_run._comparison_summary → comparison.per_sentence with a {key:band}
// `bands` map) into the per-sentence agreement rows the visuals consume,
// deriving flagged_by (AI-ish bands) without fabricating anything.
describe('buildAgreementRows — adapts the backend comparison shape (R61)', () => {
  it('derives flagged_by from per-sentence bands (medium/high = flagged)', () => {
    const detection = {
      comparison: {
        per_sentence: [
          { text: 'Both flag this.', bands: { desklib: 'high', mage: 'medium' }, detector_count: 2 },
          { text: 'Only one flags.', bands: { desklib: 'high', mage: 'low' }, detector_count: 2 },
          { text: 'Nobody flags.', bands: { desklib: 'low', mage: 'low' }, detector_count: 2 },
        ],
      },
    }
    const rows = buildAgreementRows(detection)
    expect(rows).toHaveLength(3)
    expect(rows[0].flagged_by.sort()).toEqual(['desklib', 'mage'])
    expect(rows[1].flagged_by).toEqual(['desklib'])
    expect(rows[2].flagged_by).toEqual([]) // no fabricated flag
    // detector_count (how many ASSESSED) is preserved for the denominator.
    expect(rows[0].detector_count).toBe(2)
  })

  it('passes through a legacy flagged_by array untouched', () => {
    const rows = buildAgreementRows({ agreement: [{ text: 't', flagged_by: ['desklib'] }] })
    expect(rows).toEqual([{ text: 't', flagged_by: ['desklib'], detector_count: undefined }])
  })

  it('returns null when there is no comparison/agreement data', () => {
    expect(buildAgreementRows({})).toBeNull()
    expect(buildAgreementRows(null)).toBeNull()
    expect(buildAgreementRows({ comparison: { per_sentence: [] } })).toBeNull()
  })
})

describe('AIDetectionPanel — renders agreement from the backend per_sentence shape (R61)', () => {
  it('shows flagged/assessed counts derived from real bands (no fabrication)', () => {
    const detection = {
      band: 'high',
      overall_score: 0.9,
      summary: 'Two detectors ran.',
      disclaimer: 'Advisory only.',
      detectors: [
        { key: 'desklib', label: 'Desklib', band: 'high', overall_score: 0.9 },
        { key: 'mage', label: 'MAGE', band: 'medium', overall_score: 0.6 },
      ],
      comparison: {
        per_sentence: [
          { text: 'Both detectors flag this sentence.', bands: { desklib: 'high', mage: 'high' }, detector_count: 2 },
          { text: 'Only desklib flags this one.', bands: { desklib: 'high', mage: 'low' }, detector_count: 2 },
        ],
      },
    }
    render(<AIDetectionPanel detection={detection} checkId={5} />)
    const rows = screen.getAllByTestId('agreement-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('2/2')).toBeInTheDocument() // both flagged
    expect(within(rows[1]).getByText('1/2')).toBeInTheDocument() // one flagged
  })
})
