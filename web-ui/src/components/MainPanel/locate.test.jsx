import { describe, expect, it } from 'vitest'

// The pdfjs worker/module imports are stubbed here too so importing the module
// (for its exported `locate`) never touches the real worker.
import { vi } from 'vitest'
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker-stub' }))
vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument: () => ({}), Util: {} }))
vi.mock('../../utils/api', () => ({ getPaperPdf: vi.fn() }))
vi.mock('../../utils/logger', () => ({ logger: { debug: vi.fn(), error: vi.fn() } }))

import { locate } from './NativePdfViewer'

describe('locate() quote matching', () => {
  it('finds an exact case-insensitive substring', () => {
    const page = 'Some intro. The method rose in the 1990s. More text.'
    const r = locate(page, 'the method rose in the 1990s')
    expect(r).not.toBeNull()
    expect(page.slice(r[0], r[1]).toLowerCase()).toContain('the method rose in the 1990s')
  })

  it('bridges hyphenation and merged spaces the whitespace regex cannot (real-world PDF artifacts)', () => {
    // pdf.js text-layer concatenation keeps hyphenation ("de- veloped") and the
    // backend quote merges spaces ("onstatistical"); the citation marker shows as
    // an en-dash on the page and a hyphen in the quote. Only the alnum fallback,
    // which strips all of that, can line the two up.
    const page = 'materials for pub SLMs [6–9] are de- veloped on statistical learning methods that rose in the 1990s.'
    const quote = 'SLMs [6-9] are developed onstatistical learningmethods that rose in the 1990s'
    const r = locate(page, quote)
    expect(r).not.toBeNull()
    // The located range should begin at the "SLMs" occurrence, not fail entirely.
    expect(page.slice(r[0]).toLowerCase()).toContain('slms')
  })

  it('returns null for too-short quotes', () => {
    expect(locate('anything at all here', 'short')).toBeNull()
  })

  it('returns null when nothing matches even under alnum normalization', () => {
    expect(locate('completely unrelated page content here', 'a wholly different sentence appears nowhere')).toBeNull()
  })
})
