const FINAL_STATUSES = ['error', 'warning', 'suggestion', 'unverified', 'verified', 'hallucination']

export const normalizeForMetadataComparison = (value) => String(value || '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

export const lastNameTokens = (authors) => (authors || [])
  .map(author => String(author || '').trim().split(/\s+/).filter(Boolean).pop()?.toLowerCase())
  .filter(Boolean)

export const llmFoundMetadataMatchesCitation = (reference = {}) => {
  const assessment = reference.hallucination_assessment || {}
  const foundAuthorsText = String(assessment.found_authors || '').toLowerCase()
  const citedLastNames = lastNameTokens(reference.authors)

  return assessment.verdict === 'LIKELY'
    && Boolean(assessment.link)
    && normalizeForMetadataComparison(assessment.found_title) === normalizeForMetadataComparison(reference.title)
    && citedLastNames.length > 0
    && citedLastNames.every(name => foundAuthorsText.includes(name))
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

  const finalized = references.filter(r => {
    const s = (r?.status || '').toLowerCase()
    if (!s || ['pending', 'checking', 'in_progress', 'queued', 'processing', 'started'].includes(s)) return false
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

  for (const r of finalized) {
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
      s === 'unverified' || s === 'hallucination' ||
      r?.errors?.some(e => e.error_type === 'unverified') ||
      likelyHallucinated
    ) {
      withUnverified += 1
    }

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