const FINAL_STATUSES = ['error', 'warning', 'suggestion', 'unverified', 'verified', 'hallucination']

export const normalizeForMetadataComparison = (value) => String(value || '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

export const lastNameTokens = (authors) => (authors || [])
  .map(author => String(author || '').trim().split(/\s+/).filter(Boolean).pop()?.toLowerCase())
  .filter(Boolean)

const normalizeAuthorTokens = (value) => normalizeForMetadataComparison(value)
  .split(' ')
  .filter(Boolean)

const parseFoundAuthors = (value) => {
  const text = String(value || '').trim()
  if (!text || text.toUpperCase() === 'NONE') return []

  if (text.includes(';')) {
    return text.split(';').map(author => author.trim()).filter(Boolean)
  }

  return text.split(',').map(author => author.trim()).filter(Boolean)
}

const authorMatches = (citedAuthor, foundAuthor) => {
  const citedTokens = normalizeAuthorTokens(citedAuthor)
  const foundTokens = normalizeAuthorTokens(foundAuthor)
  if (citedTokens.length === 0 || foundTokens.length === 0) return false

  const citedLast = citedTokens[citedTokens.length - 1]
  const foundLast = foundTokens[foundTokens.length - 1]
  if (citedLast !== foundLast) return false

  const cited = citedTokens.join(' ')
  const found = foundTokens.join(' ')
  if (cited === found || cited.includes(found) || found.includes(cited)) return true

  const citedGivenTokens = citedTokens.slice(0, -1).filter(token => token.length > 1)
  const foundGivenTokens = new Set(foundTokens.slice(0, -1).filter(token => token.length > 1))
  return citedGivenTokens.some(token => foundGivenTokens.has(token))
}

const authorsSubstantiallyMatch = (citedAuthors, foundAuthorsText) => {
  const cited = (citedAuthors || []).filter(Boolean)
  const found = parseFoundAuthors(foundAuthorsText)
  if (cited.length === 0 || found.length === 0) return false

  const matchedCount = cited.filter(citedAuthor => (
    found.some(foundAuthor => authorMatches(citedAuthor, foundAuthor))
  )).length

  const requiredMatches = cited.length >= 3 ? cited.length - 1 : cited.length
  return matchedCount >= requiredMatches
}

export const llmFoundMetadataMatchesCitation = (reference = {}) => {
  const assessment = reference.hallucination_assessment || {}

  return assessment.verdict === 'LIKELY'
    && Boolean(assessment.link)
    && normalizeForMetadataComparison(assessment.found_title) === normalizeForMetadataComparison(reference.title)
    && authorsSubstantiallyMatch(reference.authors, assessment.found_authors)
    && (!reference.year || String(assessment.found_year || '').includes(String(reference.year)))
}

export const getEffectiveReferenceStatus = (reference = {}, isCheckComplete = false) => {
  const baseStatus = (reference.status || '').trim().toLowerCase()
  const llmMatch = llmFoundMetadataMatchesCitation(reference)

  if (reference.hallucination_check_pending && !reference.hallucination_assessment) {
    return 'checking'
  }

  if (baseStatus === 'unverified' && !reference.hallucination_assessment && !isCheckComplete) {
    return 'checking'
  }

  // Explicit false-hallucination override: if LLM-found metadata clearly matches
  // the citation, treat it as verified even when backend labeled hallucination.
  if (baseStatus === 'hallucination' && llmMatch) {
    return 'verified'
  }

  // Precedence: hallucination > error > warning > suggestion
  if (baseStatus === 'hallucination') {
    return 'hallucination'
  }

  if (llmMatch) {
    return Array.isArray(reference.suggestions) && reference.suggestions.length > 0
      ? 'suggestion'
      : 'verified'
  }

  const hasErrors = Array.isArray(reference.errors) && reference.errors.some(
    e => (e?.error_type || '').toLowerCase() !== 'unverified'
  )
  const hasWarnings = Array.isArray(reference.warnings) && reference.warnings.length > 0
  const hasSuggestions = Array.isArray(reference.suggestions) && reference.suggestions.length > 0

  if (hasErrors) return 'error'
  if (hasWarnings) return 'warning'
  if (hasSuggestions) return 'suggestion'

  if (baseStatus === 'error' || baseStatus === 'warning' || baseStatus === 'suggestion') {
    return 'verified'
  }

  if (FINAL_STATUSES.includes(baseStatus)) {
    return baseStatus
  }

  if (baseStatus === 'pending' || baseStatus === 'checking' ||
      ['in_progress', 'queued', 'processing', 'started'].includes(baseStatus)) {
    if (isCheckComplete) {
      return 'unchecked'
    }
    return baseStatus === 'pending' ? 'pending' : 'checking'
  }

  return 'verified'
}


/**
 * Compute reference-level summary stats from a list of references.
 *
 * Single source of truth used by both the main paper Summary
 * (StatsSection) and the sidebar history card (HistoryItem) so the
 * two surfaces never disagree.
 *
 * Returns counts of:
 *   - totalProcessed: refs that have left the pending/checking state
 *   - count: refs that have a "finalized" status (no LLM check pending)
 *   - errorsCount/warningsCount/suggestionsCount: total individual issue items
 *   - withErrors/withWarnings/withSuggestions: per-ref bucket counts using
 *     getEffectiveReferenceStatus (so hallucinated refs are excluded from
 *     the error/warning bucket, suggestion-only refs from suggestions, etc.)
 *   - withUnverified, hallucinated, verified: per-ref status buckets
 */
export const computeReferenceStats = (references = [], isCheckComplete = false) => {
  if (!Array.isArray(references) || references.length === 0) {
    return null
  }

  const totalProcessed = references.filter(r => {
    const s = (r?.status || '').toLowerCase()
    if (!s || ['pending', 'checking', 'in_progress', 'queued', 'processing', 'started'].includes(s)) return false
    return true
  }).length

  const processed = references.filter(r => {
    const s = (r?.status || '').toLowerCase()
    if (!s || ['pending', 'checking', 'in_progress', 'queued', 'processing', 'started'].includes(s)) return false
    return true
  })

  const finalized = processed.filter(r => {
    const s = (r?.status || '').toLowerCase()
    if (r?.hallucination_check_pending && !r?.hallucination_assessment) return false
    if (s === 'unverified' && !r?.hallucination_assessment && !isCheckComplete) return false
    return true
  })

  let errorsCount = 0
  let warningsCount = 0
  let suggestionsCount = 0
  let withErrors = 0
  let withWarnings = 0
  let withSuggestions = 0
  let withUnverified = 0
  let hallucinated = 0
  let verified = 0

  for (const r of processed) {
    const s = getEffectiveReferenceStatus(r, isCheckComplete)
    const llmMatch = llmFoundMetadataMatchesCitation(r)
    const likelyHallucinated =
      r?.hallucination_assessment?.verdict === 'LIKELY' && !llmMatch

    // Hallucinated refs contribute their per-issue items only to the
    // hallucinated bucket, not to errors/warnings (those error entries
    // are evidence of the hallucination).
    if (s !== 'hallucination' && !llmMatch) {
      errorsCount += (r?.errors?.filter(e => e.error_type !== 'unverified') || []).length
      warningsCount += (r?.warnings || []).length
    }
    if (s !== 'hallucination') {
      suggestionsCount += (r?.suggestions || []).length
    }

    if (s === 'error') withErrors += 1
    else if (s === 'warning') withWarnings += 1
    else if (s === 'suggestion') withSuggestions += 1

    if (
      s === 'unverified' ||
      (s !== 'checking' && r?.errors?.some(e => e.error_type === 'unverified')) ||
      // A ref backend-labeled `status === 'unverified'` that hasn't yet
      // entered the hallucination LLM phase has its effective status
      // overridden to 'checking' (see getEffectiveReferenceStatus L76)
      // so the row shows a spinner. The Summary chip still needs to
      // show the count so the user knows how many refs are coming up
      // for that second-pass check. We DO NOT count refs flagged with
      // hallucination_check_pending=true — those are transient,
      // mid-LLM-call, and would otherwise double-flicker the badge.
      (r?.status === 'unverified' && !r?.hallucination_assessment &&
        !r?.hallucination_check_pending && s === 'checking')
    ) {
      withUnverified += 1
    }

    // v0.7.59: hallucinated refs are counted ONLY in the hallucinated
    // bucket, not also under unverified. Before this, every LIKELY
    // ref bumped BOTH chips, so 5 halluc + 10 unverified out of 50
    // refs totalled 65 — the user reported "badge counts inside
    // each article don't match the summary". Hallucination is a more
    // severe verdict than unverified; surfacing it in two places
    // exaggerated the bad-count surface.
    if (s === 'hallucination' || likelyHallucinated) {
      hallucinated += 1
    }

    if (s === 'verified' || s === 'suggestion') {
      verified += 1
    }
  }

  return {
    count: finalized.length,
    totalProcessed,
    errorsCount,
    warningsCount,
    suggestionsCount,
    withErrors,
    withWarnings,
    withSuggestions,
    withUnverified,
    hallucinated,
    verified,
  }
}

const numberOr = (value, fallback = 0) => (
  typeof value === 'number' && Number.isFinite(value) ? value : fallback
)

/**
 * Build the display summary used by the main Summary and history cards.
 *
 * This is the single frontend source of truth for visible count surfaces:
 * - total_refs / processed_refs come from backend progress stats
 * - reference buckets and issue totals come from reference objects when present
 * - stored aggregate stats are only fallbacks when references are unavailable
 */
export const buildReferenceSummary = ({ stats = {}, references = [], isComplete = false } = {}) => {
  const refs = Array.isArray(references) ? references : []
  const derived = refs.length > 0 ? computeReferenceStats(refs, isComplete) : null
  const rawTotalRefs = numberOr(stats.total_refs, refs.length)
  const rawProcessedRefs = stats.processed_refs !== undefined
    ? numberOr(stats.processed_refs)
    : (isComplete && rawTotalRefs > 0 ? rawTotalRefs : numberOr(derived?.totalProcessed))

  // total_refs may be an early extraction estimate; the real reference set
  // (after de-dup/merge/re-extraction) can be larger, which would make
  // processed exceed total and render >100% ("28/23 · 122%"). Reconcile the
  // displayed total up to processed so the count and the bar stay honest, and
  // clamp the percent at 100. REAL DATA ONLY — this never invents references,
  // it just stops the denominator from lagging the numerator.
  const totalRefs = Math.max(rawTotalRefs, rawProcessedRefs)
  // Defensive clamp so the visible "X / Y" can never read X > Y.
  const processedRefs = Math.min(rawProcessedRefs, totalRefs)

  return {
    totalRefs,
    processedRefs,
    progressPercent: totalRefs > 0 ? Math.min((processedRefs / totalRefs) * 100, 100) : 0,
    references: {
      verified: derived?.verified ?? numberOr(stats.refs_verified, numberOr(stats.verified_count)),
      errors: derived?.withErrors ?? numberOr(stats.refs_with_errors),
      warnings: derived?.withWarnings ?? numberOr(stats.refs_with_warnings_only),
      suggestions: derived?.withSuggestions ?? numberOr(stats.refs_with_suggestions_only),
      unverified: derived?.withUnverified ?? numberOr(stats.unverified_count),
      hallucinated: derived?.hallucinated ?? numberOr(stats.hallucination_count),
    },
    issues: {
      errors: derived?.errorsCount ?? numberOr(stats.errors_count),
      warnings: derived?.warningsCount ?? numberOr(stats.warnings_count),
      suggestions: derived?.suggestionsCount ?? numberOr(stats.suggestions_count),
      unverified: derived?.withUnverified ?? numberOr(stats.unverified_count),
      hallucinated: derived?.hallucinated ?? numberOr(stats.hallucination_count),
    },
  }
}
/**
 * Apply the multi-select status filter (the Summary chips) to a list of
 * references and return the subset that matches.
 *
 * Shared between the References tab (so the tab pill count matches the
 * inline "Showing X" label) and the per-tab content list.
 */
export function applyStatusFilter(references, statusFilter, isCheckComplete = false) {
  const filters = (statusFilter || []).map(f => String(f).toLowerCase())
  if (filters.length === 0) return references || []
  return (references || []).filter(ref => {
    const status = (getEffectiveReferenceStatus(ref, isCheckComplete) || '').toLowerCase()
    const hasMetaMatch = llmFoundMetadataMatchesCitation(ref)
    return filters.some(filter => {
      switch (filter) {
        case 'verified':
          return status === 'verified' || status === 'suggestion'
        case 'error':
          if (status === 'hallucination') return false
          if (hasMetaMatch) return false
          return (ref.errors || []).some(e => e.error_type !== 'unverified')
        case 'warning':
          if (status === 'hallucination') return false
          if (hasMetaMatch) return false
          return (ref.warnings || []).length > 0
        case 'suggestion':
          return (ref.suggestions || []).length > 0
        case 'unverified':
          if (status === 'checking') return false
          if (status === 'unverified' || status === 'hallucination') return true
          if ((ref.errors || []).some(e => e.error_type === 'unverified')) return true
          return ref.hallucination_assessment?.verdict === 'LIKELY' && !hasMetaMatch
        case 'hallucination':
          if (status === 'hallucination') return true
          return ref.hallucination_assessment?.verdict === 'LIKELY' && !hasMetaMatch
        default:
          return status === filter
      }
    })
  })
}
