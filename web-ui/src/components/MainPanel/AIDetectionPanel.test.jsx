import { describe, expect, it } from 'vitest'
import { buildViewerSpans } from './AIDetectionPanel'

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
