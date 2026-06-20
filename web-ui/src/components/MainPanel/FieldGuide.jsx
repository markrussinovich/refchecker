import { useState } from 'react'

/**
 * Field-specific guidance shown on the input screen. Static, factual guidance
 * about which identifiers/sources matter per discipline and how RefChecker
 * treats them — NOT generated or example data. Dismissible per-browser.
 */
const DISMISS_KEY = 'refchecker.fieldguide.dismissed.v1'

const FIELDS = [
  {
    id: 'ml', label: 'ML / CS', tips: [
      'Many citations are arXiv preprints — paste an arXiv ID/URL or upload the PDF; arXiv, DBLP and Semantic Scholar are queried.',
      'Conference papers (NeurIPS, ICML, ACL) often have no DOI; title + venue + year matching carries the verification.',
      'Preprint-vs-published drift shows as a minor year/venue note, not an error.',
    ],
  },
  {
    id: 'medicine', label: 'Medicine / Biology', tips: [
      'Cited works usually have a PMID and/or DOI — PubMed, Crossref and OpenAlex are cross-checked.',
      'NLM journal abbreviations and "et al." truncation are common; these are downweighted as minor warnings.',
      'Run "Check for retractions" after a check — clinical citations are where a retracted source matters most.',
    ],
  },
  {
    id: 'physics', label: 'Physics / Astro', tips: [
      'arXiv identifiers verify directly; large-collaboration author lists are matched leniently.',
      'A single-name "et al." against a hundred-author paper will not be flagged.',
    ],
  },
  {
    id: 'social', label: 'Social science / Humanities', tips: [
      'Books, chapters and reports may have no DOI; title + author + year + publisher matching is used, and "unverified" does not mean "wrong".',
      'Page/edition specifics are not auto-verified — review those manually.',
    ],
  },
]

export default function FieldGuide() {
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISS_KEY) === '1' } catch { return false }
  })
  const [active, setActive] = useState('ml')
  if (dismissed) return null
  const field = FIELDS.find((f) => f.id === active) || FIELDS[0]
  const dismiss = () => { try { localStorage.setItem(DISMISS_KEY, '1') } catch { /* ignore */ } setDismissed(true) }

  return (
    <div className="mb-3 rounded-lg p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>
          Field guide
        </div>
        <button type="button" onClick={dismiss} className="text-xs" style={{ color: 'var(--color-text-muted)' }} title="Dismiss">Dismiss</button>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {FIELDS.map((f) => (
          <button key={f.id} type="button" onClick={() => setActive(f.id)}
            className="px-2.5 py-1 rounded-full text-xs border transition-colors"
            style={active === f.id
              ? { background: 'var(--color-accent)', color: '#fff', borderColor: 'var(--color-accent)' }
              : { background: 'transparent', color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' }}>
            {f.label}
          </button>
        ))}
      </div>
      <ul className="space-y-1">
        {field.tips.map((t, i) => (
          <li key={i} className="flex items-start gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <span style={{ color: 'var(--color-accent)', marginTop: 1 }}>•</span>
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
