import { useEffect, useState } from 'react'
import { getPaperAuthors } from '../../utils/api'
import { AuthorsLine } from '../ReferenceCard/ReferenceCard'

const SOURCE_NAMES = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', arxiv: 'arXiv' }

export default function PaperAuthors({ checkId }) {
  const [result, setResult] = useState({ loading: true, data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setResult({ loading: true, data: null, error: null })
    getPaperAuthors(checkId)
      .then(({ data }) => {
        if (active) setResult({ loading: false, data, error: null })
      })
      .catch(error => {
        if (active) setResult({
          loading: false, data: null,
          error: error?.response?.data?.detail || error.message || 'Unable to load paper authors.',
        })
      })
    return () => { active = false }
  }, [checkId, attempt])

  const authors = result.data?.authors || []
  return (
    <div className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
      {result.loading ? (
        <span role="status">Preloading paper authors and profiles...</span>
      ) : result.error ? (
        <span role="alert">{result.error}</span>
      ) : result.data?.available && authors.length > 0 ? (
        <div aria-label="Paper authors">
          <AuthorsLine
            authors={authors.map(author => author.name)}
            enrichedAuthors={authors}
            paperTitle={result.data.title}
            paperYear={result.data.year}
          />
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Authors from {SOURCE_NAMES[result.data.source] || result.data.source}.
            {' '}Hover for stats and profile links, including Google Scholar; click a linked name to open its profile.
          </span>
        </div>
      ) : (
        <span>{result.data?.reason || 'No indexed authors are available for this paper.'}</span>
      )}
      {!result.loading && (!result.data?.available || result.error) && (
        <button type="button" onClick={() => setAttempt(value => value + 1)}
          className="ml-2 underline" style={{ color: 'var(--color-accent)' }}>
          Retry author lookup
        </button>
      )}
    </div>
  )
}
